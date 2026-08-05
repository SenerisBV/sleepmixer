module Page.Renders exposing
    ( State(..), Summary
    , audioUrl, deleteMessage, durationLabel, jobFor, keepStreamed, liveRenderJob
    , minutesLabel, momentOf, newestFirst, reasonFor, replaceJob, summarise, titleFor
    , view
    )

{-| Everything you have rendered: what it was, how it went, and what to do with it.

Until this screen existed, producing a finished mix meant the command line, and
finding one afterwards meant `ls ~/.sleepmix/renders` and a filename that is a
hex id. So the job here is not "list some rows" — it is to make a directory of
identically-named WAVs legible again.

**That is what the config summary is for.** Six renders of the same song show
six identical titles, and the thing that actually distinguishes them is the
config each was rendered with: how long the mix is, which stems were playing,
and how far the decay travels by the end. Those three are on the row; the whole
stored config is one click away under it.

**Nothing here invents a value it cannot see.** `config` is whatever was
`POST`ed, and the server accepts `{}` — a render made that way used
`MixConfig`'s own defaults, which are applied server-side where this screen
cannot read them. So an absent key summarises as "not recorded" rather than as
the default it probably was. Claiming a default we did not see would make two
renders look identical when only one of them stated anything.

**The audition is a plain `<audio controls>`, not the Web Audio port.** That
port decodes an entire buffer into memory so it can loop it on a musical seam,
which is right for a five-second preview and wrong for half an hour of WAV —
roughly 300 MB decoded, to play a file the browser will happily stream. An
`<audio>` element costs no JavaScript at all.

-}

import Api
import Html exposing (Attribute, Html, a, audio, button, details, div, h2, p, pre, span, summary, text)
import Html.Attributes as Attr exposing (class, href)
import Html.Events exposing (onClick)
import Http
import Json.Decode as Decode exposing (Decoder)
import Json.Encode as Encode
import Url.Builder


{-| The fetch behind the screen. A union rather than a list beside an error
string, for the reason `Page.Library.State` gives: "loading", "loaded but
empty" and "failed" are three different things to say, and the fourth
combination a pair of fields would allow is not a state.
-}
type State
    = Loading
    | Loaded (List Api.Render)
    | Failed String



-- THE JOIN


{-| The song this render was made from, by whatever name we can give it.

Falls back to the song id rather than to an empty cell or to "unknown": a
render outlives the song row it came from — importing is undoable, rendering is
not — and the id is the only remaining handle on which file it was. A blank
title would leave a row that cannot be told apart from any other orphan.
-}
titleFor : List Api.Song -> String -> String
titleFor songs songId =
    case List.filter (\s -> s.id == songId) songs of
        found :: _ ->
            found.title

        [] ->
            songId


{-| Newest first, said by the screen rather than assumed of the endpoint.

`GET /api/renders` already answers `ORDER BY created_at DESC`, so this changes
nothing today. It is here because "newest first" is a property of the list
someone is reading, and one that should not quietly depend on a SQL clause in
another language. `created_at` is a UTC `datetime.isoformat()` throughout, so
the strings sort in the same order as the instants they name.
-}
newestFirst : List Api.Render -> List Api.Render
newestFirst renders =
    List.reverse (List.sortBy .createdAt renders)


{-| The job that produced this render, if the manager still remembers it.

Matched on the job's own `render_id` and on nothing else. This used to be a
pairing by song and timestamp — the render row is written microseconds before
the job is submitted, so "the earliest render-kind job for this song at or after
this render's `created_at`" is right whenever both rows exist. The case where
they do not is the whole problem: jobs are held in memory and renders in SQLite,
so a server restarted mid-render leaves that render at `running` forever with no
job of its own and no counterpart to `reconcile_orphaned_separations` to clear
it. Render the same song again and the stranded row matched the *new* job:
it drew the live render's progress bar and its Cancel button carried the live
render's job id, so cancelling what looked like a dead row killed the render
that was actually running and `_abandon` deleted its file. Silently, with both
rows showing the same bar.

An id cannot do that. A render with no job of its own now matches nothing,
which is the state `inFlight` already had a branch and a sentence for.

This is also the only route to why a failed render failed. The render row
records the status and not the reason — `store.renders` has no column for one —
so the sentence a failed row shows comes from the job's `error`, for as long as
the manager keeps it (fifty terminal jobs, and none across a restart).
-}
jobFor : List Api.Job -> Api.Render -> Maybe Api.Job
jobFor jobs render =
    List.head (List.filter (\aJob -> aJob.renderId == Just render.id) jobs)


{-| The one render job worth holding an event stream open for.

One worker runs everything, so at most one render is genuinely moving; the
running one if there is one, and otherwise the oldest still waiting, which is
the one that will move next. Terminal jobs are excluded — their stream would
deliver a snapshot and close, which is not progress.
-}
liveRenderJob : List Api.Job -> Maybe Api.Job
liveRenderJob jobs =
    let
        live =
            jobs
                |> List.filter (\aJob -> aJob.kind == "render" && not (Api.isFinished aJob.status))
                |> List.sortBy .createdAt
    in
    case List.filter (\aJob -> aJob.status == Api.Running) live of
        running :: _ ->
            Just running

        [] ->
            List.head live


{-| A polled job list with one job's fresher state written over it.

`GET /api/jobs` is a snapshot taken when the screen opened; the event stream
keeps exactly one of those entries moving. Replacing in place rather than
prepending keeps the list in the order it was polled in, so a row does not jump
because its progress changed.

A job the snapshot does not contain is added rather than discarded. That should
not happen — the stream is only ever opened on a job the snapshot named — but
dropping it would freeze a bar at whatever the poll last said while the render
carried on behind it, and a bar that has quietly stopped meaning anything is
worse than no bar.
-}
replaceJob : Api.Job -> List Api.Job -> List Api.Job
replaceJob incoming jobs =
    if List.any (\existing -> existing.id == incoming.id) jobs then
        List.map
            (\existing ->
                if existing.id == incoming.id then
                    incoming

                else
                    existing
            )
            jobs

    else
        jobs ++ [ incoming ]


{-| A freshly polled job list, without undoing the streamed job's progress.

`GET /api/jobs` is a snapshot of a moment, and its response can arrive after an
event that describes a later one — the poll is a round trip and the stream is a
push. Taking the polled copy wholesale then moves the bar backwards, from 70%
to the 30% the server had reached when the snapshot was taken.

So the one job an event stream is open on keeps whatever this side already
holds, and every other job takes the polled value. Exactly one job can be in
that position, and it is the only one whose progress moves at all: one worker
runs everything, and every other row is waiting or finished.
-}
keepStreamed : Maybe String -> List Api.Job -> List Api.Job -> List Api.Job
keepStreamed streaming held polled =
    let
        streamedCopy =
            case streaming of
                Just id ->
                    List.head (List.filter (\existing -> existing.id == id) held)

                Nothing ->
                    Nothing
    in
    case streamedCopy of
        Nothing ->
            polled

        Just streamed ->
            List.map
                (\fresh ->
                    if fresh.id == streamed.id then
                        streamed

                    else
                        fresh
                )
                polled



-- THE SUMMARY


{-| The three things that differ between two renders of the same song.

Strings rather than numbers because every one of them has an honest absent
case, and "not recorded" is a thing the row has to be able to say in the same
place a value would have gone.
-}
type alias Summary =
    { length : String
    , stems : String
    , decay : String
    }


summarise : Decode.Value -> Summary
summarise config =
    { length = lengthSummary config
    , stems = stemSummary config
    , decay = decaySummary config
    }


lengthSummary : Decode.Value -> String
lengthSummary config =
    case Decode.decodeValue (Decode.at [ "output", "duration_min" ] Decode.float) config of
        Ok minutes ->
            minutesLabel minutes

        Err _ ->
            "length not recorded"


{-| How long the finished file is, as the render row states it.

`duration_min` is `NULL` until the render finishes, and stays that way forever
on one that failed or was cancelled — so `Nothing` is "nobody ever measured
this", which is a different sentence from "it is zero minutes long". A render
that never produced a file must not read as one that produced an empty one.
-}
durationLabel : Maybe Float -> String
durationLabel duration =
    case duration of
        Just minutes ->
            minutesLabel minutes

        Nothing ->
            "length not recorded"


{-| Minutes, or seconds when there is less than a minute of it.

A whole-minute rounding alone would render the 0.05-minute configs this
project's own tests use as "0 min", which reads as a bug in the renderer rather
than as a three-second file.

Exposed as well as used here, because `Page.Mixer`'s pre-flight line states the
length of the mix it is *about* to render and this screen states the length of
the file that came out. Two answers to "how long is this mix" that could
disagree — one saying "0 min" where the other said "3 s" — would be exactly the
drift `Page.Queue` avoids by taking `titleFor` from here rather than copying it.
-}
minutesLabel : Float -> String
minutesLabel minutes =
    if minutes >= 1 then
        String.fromInt (round minutes) ++ " min"

    else
        String.fromInt (round (minutes * 60)) ++ " s"


type alias StemEntry =
    { name : String
    , enabled : Bool
    , decaying : Bool
    , lowpassEnd : Maybe Float
    }


{-| A stem as the stored config carries it.

`enabled` absent means enabled, which is `StemConfig`'s own default and the
only reading under which a config that never mentions the key means "play it" —
`Page.Mixer.stemEnabled` makes the same call for the same reason. That is not
the same as inventing a default for a key nobody wrote: this one decides how to
read a stem the config *does* list, rather than conjuring a stem list that is
not there.
-}
stemEntry : Decoder StemEntry
stemEntry =
    Decode.map4 StemEntry
        (Decode.field "name" Decode.string)
        (withDefault True (Decode.field "enabled" Decode.bool))
        (withDefault True (Decode.at [ "decay", "enabled" ] Decode.bool))
        (Decode.maybe (Decode.at [ "decay", "lowpass_end_hz" ] Decode.float))


withDefault : a -> Decoder a -> Decoder a
withDefault fallback decoder =
    Decode.oneOf [ decoder, Decode.succeed fallback ]


stems : Decode.Value -> Maybe (List StemEntry)
stems config =
    Decode.decodeValue (Decode.field "stems" (Decode.list stemEntry)) config
        |> Result.toMaybe


stemSummary : Decode.Value -> String
stemSummary config =
    case stems config of
        Nothing ->
            "stems not recorded"

        Just entries ->
            case List.map .name (List.filter .enabled entries) of
                [] ->
                    "every stem switched off"

                names ->
                    String.join " · " names


{-| Where the erosion ends up, which is the whole point of the thing.

The lowpass endpoint rather than any of the other four, because it is the one
you hear: the mix gets darker as it repeats, and this says how dark. Stems
usually differ — the CLI's defaults take vocals further down than `other` — so
a range is stated rather than one stem's value passed off as the mix's.

A stem whose decay is switched off contributes no endpoint, because it does not
travel; if none of them do, the mix repeats unchanged and the row says so.

**And a stem that is switched off contributes nothing either, decaying or not.**
It is not in the mix, so where its decay would have ended is not a fact about
anything anyone hears. Both halves of that matter and both were wrong: a config
with vocals on at 2200 Hz and a disabled bass at 1600 Hz read `decays to
1.6–2.2 kHz` for a mix whose only audible stem stops at 2.2 kHz, and one whose
enabled stems all had decay switched off still claimed a decay if some disabled
stem carried one.
-}
decaySummary : Decode.Value -> String
decaySummary config =
    case stems config of
        Nothing ->
            "decay not recorded"

        Just entries ->
            let
                decaying =
                    List.filter (\entry -> entry.enabled && entry.decaying) entries

                ends =
                    List.filterMap .lowpassEnd decaying
            in
            if List.isEmpty decaying then
                "no decay"

            else
                case ( List.minimum ends, List.maximum ends ) of
                    ( Just low, Just high ) ->
                        "decays to " ++ range low high

                    _ ->
                        "decay endpoint not recorded"


{-| One frequency, or two with the unit said once when both carry the same one.
-}
range : Float -> Float -> String
range low high =
    if low == high then
        hertz low

    else if unitOf low == unitOf high then
        magnitude low ++ "–" ++ hertz high

    else
        hertz low ++ "–" ++ hertz high


hertz : Float -> String
hertz value =
    magnitude value ++ " " ++ unitOf value


magnitude : Float -> String
magnitude value =
    if value >= 1000 then
        String.fromFloat (toFloat (round (value / 100)) / 10)

    else
        String.fromInt (round value)


unitOf : Float -> String
unitOf value =
    if value >= 1000 then
        "kHz"

    else
        "Hz"



-- THE THINGS THAT WENT WRONG


{-| Why a render has no file, said as specifically as the record allows.

A failed render's reason lives on its job and nowhere else, so this says who is
missing rather than pretending the render simply failed for no reason — a row
that says "failed" and stops is the kind of silence this project keeps
deciding against.
-}
reasonFor : Api.RenderStatus -> Maybe Api.Job -> String
reasonFor status paired =
    case status of
        Api.RenderCancelled ->
            "Cancelled. The partial file was removed with it, so there is "
                ++ "nothing here to play or download."

        Api.RenderFailed ->
            case Maybe.map .status paired of
                Just (Api.Failed detail) ->
                    "Failed — " ++ detail

                _ ->
                    "Failed. The reason was recorded on the job that ran it "
                        ++ "rather than on the render, and that job is no longer "
                        ++ "held — jobs live in memory and do not survive a restart."

        _ ->
            ""


{-| What to say when a delete is refused.

The 409 is reachable by ordinary use: the delete button is on every row that
has ended, and a row that ended between the list being fetched and the button
being pressed is exactly the case the server refuses. Restating its reason in
the interface's own words — including that cancelling is what removes the
partial file — is the difference between an instruction and a status code.

Takes the generic wording rather than deriving it, so `Main.httpErrorToString`
stays the one place an `Http.Error` becomes English.
-}
deleteMessage : Http.Error -> String -> String
deleteMessage err detail =
    case err of
        Http.BadStatus 409 ->
            "That render is still being produced, so it cannot be deleted yet — "
                ++ "cancel it first, which removes the half-written file too."

        Http.BadStatus 404 ->
            "That render was already gone."

        _ ->
            "Could not delete that render — " ++ detail



-- ODDS AND ENDS


{-| The timestamp, to the minute.

`created_at` is a full `datetime.isoformat()` with microseconds and an offset,
which is the right thing to store and an unreadable thing to put in a row of
six. Anything not in that shape is passed through untouched rather than
truncated into nonsense.
-}
momentOf : String -> String
momentOf iso =
    case String.split "T" iso of
        [ date, rest ] ->
            date ++ " " ++ String.left 5 rest

        _ ->
            iso


{-| Built rather than concatenated, as everything in `Request.elm` is: the id
is a path segment and percent-encoding it is free.
-}
audioUrl : String -> String
audioUrl renderId =
    Url.Builder.absolute [ "api", "renders", renderId, "audio" ] []



-- VIEW


type alias Config msg =
    { state : State
    , songs : List Api.Song
    , jobs : List Api.Job
    , problem : Maybe String
    , onDelete : String -> msg
    , onCancel : String -> msg
    , onBack : msg
    }


view : Config msg -> Html msg
view config =
    div [ class "renders" ]
        -- "Back" rather than a destination: closing this screen returns you to
        -- whichever one you opened it from, which is the library today and the
        -- mixer once a render can be started from there. A button naming a
        -- screen it cannot know it is going to is a small lie told every time.
        [ button [ class "back", onClick config.onBack ] [ text "← Back" ]
        , h2 [] [ text "Renders" ]
        , problemLine config.problem
        , body config
        ]


problemLine : Maybe String -> Html msg
problemLine problem =
    case problem of
        Just words ->
            p [ class "error" ] [ text words ]

        Nothing ->
            text ""


body : Config msg -> Html msg
body config =
    case config.state of
        Loading ->
            p [ class "dim" ] [ text "Loading what you have rendered…" ]

        Failed reason ->
            p [ class "error" ] [ text ("Could not load your renders — " ++ reason) ]

        Loaded [] ->
            p [ class "dim" ]
                [ text
                    ("Nothing rendered yet. A finished mix appears here — with the "
                        ++ "config it was made from — once one has been rendered."
                    )
                ]

        Loaded rows ->
            div [ class "render-list" ] (List.map (row config) (newestFirst rows))


row : Config msg -> Api.Render -> Html msg
row config render =
    let
        paired =
            jobFor config.jobs render
    in
    div [ class "render-row" ]
        (div [ class "render-head" ]
            [ span [ class "render-title" ] [ text (titleFor config.songs render.songId) ]
            , span (statusClass render.status) [ text (Api.renderStatusLabel render.status) ]
            , span [ class "render-when" ] [ text (momentOf render.createdAt) ]
            ]
            :: summaryLine render
            :: outcome config paired render
            ++ [ configDetails render ]
        )


{-| Two whole class strings rather than one assembled from pieces — see
`Page.Mixer.soloClass` for why, and `tests/test_static_bundle.py` for what
enforces it.

`render-bad` rather than the page's existing `.error`, and that is a selector
decision rather than a naming one. The stylesheet writes the status rule as
`.renders .render-status`, which is 0-2-0; `.error` is 0-1-0. So `.error` added
to a status span loses on **specificity**, not on order — stating it later in
the file would not rescue it, and a failed render would read in the dim of an
ordinary one however the stylesheet were arranged. A second class scoped the
same way the status is, `.renders .render-bad`, ties on specificity and wins on
order, which is a thing the file can actually control.
-}
statusClass : Api.RenderStatus -> List (Attribute msg)
statusClass status =
    case status of
        Api.RenderFailed ->
            [ class "render-status render-bad" ]

        Api.RenderCancelled ->
            [ class "render-status render-bad" ]

        _ ->
            [ class "render-status" ]


summaryLine : Api.Render -> Html msg
summaryLine render =
    let
        summary =
            summarise render.config
    in
    p [ class "render-summary" ]
        [ span [ class "render-fact" ] [ text summary.length ]
        , span [ class "render-fact" ] [ text summary.stems ]
        , span [ class "render-fact" ] [ text summary.decay ]
        ]


outcome : Config msg -> Maybe Api.Job -> Api.Render -> List (Html msg)
outcome config paired render =
    case render.status of
        Api.RenderDone ->
            finished config render

        Api.RenderQueued ->
            inFlight config paired

        Api.RenderRunning ->
            inFlight config paired

        Api.RenderFailed ->
            ended config paired render

        Api.RenderCancelled ->
            ended config paired render


{-| A finished mix: take it away, or hear where it got to.

`download` carries no filename of its own — the server already answers with a
`Content-Disposition` naming the file, and a name written here would be a
second opinion about it that could drift.
-}
finished : Config msg -> Api.Render -> List (Html msg)
finished config render =
    [ div [ class "render-actions" ]
        [ a [ class "download", href (audioUrl render.id), Attr.download "" ]
            [ text "Download" ]
        , span [ class "dim" ] [ text (durationLabel render.durationMin ++ " of audio") ]
        , button [ class "delete", onClick (config.onDelete render.id) ] [ text "Delete" ]
        ]
    , audio
        [ class "render-audio"
        , Attr.controls True
        , Attr.src (audioUrl render.id)
        , Attr.preload "none"
        ]
        []
    ]


{-| Queued or running, which differ only in whether the bar has moved.

Without a job there is no progress to draw and nothing to cancel with, and that
is a real state rather than an error: the manager holds its jobs in memory, so
a render still marked running after the server was restarted has no job behind
it and never will. Saying which of those it is beats an empty bar.
-}
inFlight : Config msg -> Maybe Api.Job -> List (Html msg)
inFlight config paired =
    case paired of
        Just aJob ->
            [ progressBar aJob.fraction
            , div [ class "render-actions" ]
                [ button [ class "cancel", onClick (config.onCancel aJob.id) ]
                    [ text "Cancel" ]
                , span [ class "dim" ] [ text (jobLine aJob) ]
                ]
            ]

        Nothing ->
            [ p [ class "dim" ]
                [ text
                    ("Still marked as being produced, but there is no job behind it. "
                        ++ "The queue is held in memory, so a render caught by a server "
                        ++ "restart keeps this status with nothing left to cancel — and "
                        ++ "the server refuses to delete a render at this status, so "
                        ++ "there is nothing this screen can do with the row either. "
                        ++ "The file, if there is one, is in the renders directory; "
                        ++ "render the song again to get a finished one."
                    )
                ]
            ]


jobLine : Api.Job -> String
jobLine aJob =
    if String.isEmpty aJob.message then
        "Waiting for the worker — one render runs at a time."

    else
        aJob.message


ended : Config msg -> Maybe Api.Job -> Api.Render -> List (Html msg)
ended config paired render =
    [ p [ class "render-bad" ] [ text (reasonFor render.status paired) ]
    , div [ class "render-actions" ]
        [ button [ class "delete", onClick (config.onDelete render.id) ] [ text "Delete" ] ]
    ]


{-| A track with a fill inside it, the same shape and the same three classes
the separation panel uses — a fill carrying nothing but an inline width needs a
sibling-free parent of a known size to be a percentage of.

A render reports real fractions throughout, unlike separation, so this one
genuinely moves.
-}
progressBar : Float -> Html msg
progressBar fraction =
    div [ class "progress" ]
        [ div [ class "progress-track" ]
            [ div
                [ class "progress-fill"
                , Attr.style "width" (String.fromFloat (fraction * 100) ++ "%")
                ]
                []
            ]
        , span [ class "dim" ]
            [ text (String.fromInt (round (fraction * 100)) ++ "%") ]
        ]


{-| The whole config, folded away.

Pretty-printed from the stored value rather than described: this is the record
of what produced the file, and a summary of a summary would be the one thing on
the screen nobody could check.
-}
configDetails : Api.Render -> Html msg
configDetails render =
    details [ class "render-config" ]
        [ summary [] [ text "The config this was rendered with" ]
        , pre [ class "render-json" ] [ text (Encode.encode 2 render.config) ]
        ]
