module Page.Queue exposing
    ( State(..)
    , afterFailedPoll, cancellable, detailFor, emptyNote, kindLabel, ordered
    , staleNote, statusLabel, subject
    , view
    )

{-| Everything the one worker is doing, and everything stacked up behind it.

**One worker runs all of it.** Separations and renders go onto the same
single-threaded pool, so a long job does not slow the others down — it stops
them. The operator found this the hard way: a seventy-minute file imported by
accident, a smaller one they wanted to test instead, and no way to get at the
first except killing the server from a terminal. This screen is the way out of
that. It says what is in front of you, and it has a button that stops it.

**So the order is the answer, not decoration.** Running first, then waiting, then
what has recently ended — and inside each of those, oldest first, because that
is the order the worker will take them in. A list sorted newest-first would put
the thing you can do nothing about at the top and the thing blocking everything
at the bottom, which is the wrong way round for a screen you open when you are
stuck.

**It is live-only, and it says so.** `JobManager` holds its jobs in a dictionary
in memory; nothing is written down between runs. A restart empties this screen,
and an empty screen is then the truth rather than a failure to load. A screen
that goes blank for a structural reason and does not explain itself is the same
class of problem as a progress bar with no bar, which this project has already
shipped once.

**It refreshes by polling, and the poll lives in `Main`.** A job nobody is
watching still has to move on screen, and the alternative — an `EventSource` per
row — is ten connections to report one worker's progress, since `ports/events.js`
is built around watching a single job and the manager fans out per subscriber.
Polling a list is the right shape for a list.

-}

import Api
import Html exposing (Attribute, Html, button, div, h2, p, span, text)
import Html.Attributes as Attr exposing (class)
import Html.Events exposing (onClick)
import Page.Renders as Renders


{-| The fetch behind the screen. A union rather than a list beside an error
string, for the reason `Page.Library.State` gives: "loading", "loaded but
empty" and "failed" are three different things to say, and the fourth
combination a pair of fields would allow is not a state.

`Stale` is the fourth thing this screen has to say and the other three cannot:
rows that arrived, and a refresh since then that did not. It carries the rows
*and* the reason because both are true at once, and it is a state rather than a
warning written to a field beside `Loaded` for a reason worth stating — a field
has to be cleared by hand when the next poll succeeds, and the poll that would
have to remember is the same one that writes the fresh rows. Here the fresh rows
*are* the clearing: `Loaded` is not `Stale`.
-}
type State
    = Loading
    | Loaded (List Api.Job)
    | Stale (List Api.Job) String
    | Failed String



-- THE ORDER


{-| Where a job sits in the reading order: what is happening, what is about to,
what already did.

An `Int` rather than a union with a comparison written for it, because it is
only ever fed to `List.sortBy` — and the numbers are spaced by one on purpose so
that adding a fourth band later is a change in one place.
-}
band : Api.JobStatus -> Int
band status =
    case status of
        Api.Running ->
            0

        Api.Queued ->
            1

        Api.Done ->
            2

        Api.Cancelled ->
            2

        Api.Failed _ ->
            2


{-| In flight, then waiting, then recently ended.

Both the grouping and the sort inside it are said here rather than assumed of
`GET /api/jobs`. That endpoint answers in `JobManager`'s own insertion order,
which is submission order and therefore already `created_at` ascending, and it
does no grouping at all. So the grouping is genuinely this screen's, and the
order within a group is a property of the list someone is reading rather than
something that should quietly depend on a dictionary's iteration order in
another language.

Terminal jobs sort last however recently they ended, and that is the whole point
of banding before sorting: the fifty finished jobs the manager keeps would
otherwise bury the one that is actually blocking the worker.

**The three groups do not share one direction, and the reason is what each
group is for.** Running and waiting are ordered oldest first because that is the
order the worker will take them in — the list is a prediction, and reading down
it is reading forward in time. Nothing about that is true of the ended group:
the worker will never take those again, so "the order they will happen in" is
not a fact about them, and the only reason anyone scrolls to that group is to
read what just happened. The manager keeps fifty of them and this screen has no
pagination, so oldest-first would put a render that failed a minute ago at the
bottom of fifty rows — the exact row you opened the screen for, hidden by
forty-nine you did not. It is also what the renders screen one click away
already does with the same material.

`created_at` is a UTC `datetime.isoformat()` throughout, so the strings sort in
the same order as the instants they name, in either direction.
-}
ordered : List Api.Job -> List Api.Job
ordered jobs =
    let
        ( ended, live ) =
            List.partition (\aJob -> Api.isFinished aJob.status) jobs
    in
    List.sortBy (\aJob -> ( band aJob.status, aJob.createdAt )) live
        ++ List.reverse (List.sortBy .createdAt ended)


{-| Can this still be stopped?

Asked of the status rather than of the button, because the server asks the same
question — `JobManager.cancel` refuses a job already in a terminal status — and
a row offering a button for something that cannot happen is a row that lies
about what the screen can do.
-}
cancellable : Api.Job -> Bool
cancellable aJob =
    not (Api.isFinished aJob.status)



-- WHAT THE SCREEN SAYS


{-| The standing note under the title.

The queue is not persisted anywhere, and there is no honest way for this screen
to distinguish "the server was restarted" from "nothing has been submitted yet".
So it states the structural fact once, at the top, where it explains both.
-}
liveOnlyNote : String
liveOnlyNote =
    "One worker runs all of this, so whatever is at the top is what everything "
        ++ "below it is waiting for. The queue is held in memory for as long as "
        ++ "the server runs and is not written down anywhere between runs."


{-| What stands in place of the rows when there are none.

A `Maybe` over the list rather than a bare string, so the empty case is decided
once, in a function `elm-test` can reach, rather than inside a `case` in the
view where it cannot.
-}
emptyNote : List Api.Job -> Maybe String
emptyNote jobs =
    if List.isEmpty jobs then
        Just
            ("Nothing running and nothing waiting. If the server has just been "
                ++ "restarted this is the queue being empty rather than this "
                ++ "screen failing to load it — a restart starts the queue over, "
                ++ "and anything that was in flight is gone with it."
            )

    else
        Nothing


{-| A failed refresh, folded into whatever the screen already had.

The screen re-polls every few seconds, so a single dropped request must not
replace a list of live jobs with an error line: the rows go stale, they do not
go away. What they must not do is go on looking current — a Cancel button drawn
from a snapshot of unknown age is a button that might stop something other than
what it is next to — so the reason travels with them and the screen says both.

A first fetch that failed has nothing to keep, and `Failed` is the only honest
thing left.
-}
afterFailedPoll : String -> State -> State
afterFailedPoll reason state =
    case state of
        Loaded jobs ->
            Stale jobs reason

        Stale jobs _ ->
            -- The newer reason, over the same rows. The rows are no more stale
            -- for having failed twice, but the reason may have changed.
            Stale jobs reason

        _ ->
            Failed reason


{-| What a screen whose refresh is failing says above its rows.
-}
staleNote : String -> String
staleNote reason =
    "Could not refresh the queue — "
        ++ reason
        ++ ". What is below is from the last poll that worked, so a job may "
        ++ "have finished or started since."


{-| What kind of work this is, as a noun.

`kind` is a plain string on the wire rather than a closed union — the one field
in `Api.Job` that is — so an unrecognised value is passed through as the server
said it rather than renamed or blanked. A kind added on the Python half of a
branch whose Elm half has not shipped yet reads as itself, which is ugly and
true, instead of vanishing.
-}
kindLabel : String -> String
kindLabel kind =
    case kind of
        "separate" ->
            "separation"

        "render" ->
            "render"

        other ->
            other


statusLabel : Api.JobStatus -> String
statusLabel status =
    case status of
        Api.Queued ->
            "waiting"

        Api.Running ->
            "running"

        Api.Done ->
            "done"

        Api.Cancelled ->
            "cancelled"

        Api.Failed _ ->
            "failed"


{-| The song this job is working on, by whatever name we can give it.

`Page.Renders.titleFor` rather than a second copy of the same join: a job's
`song_id` and a render's are the same id resolved against the same library, and
two answers to that question would be one bug waiting for a song to be deleted.

`song_id` is nullable on the wire — nothing submits a job without one today, but
the decoder does not promise that — so the empty case says what it is instead of
falling through to a blank cell that reads as a song with no title.
-}
subject : List Api.Song -> Api.Job -> String
subject songs aJob =
    case aJob.songId of
        Just songId ->
            Renders.titleFor songs songId

        Nothing ->
            "no song recorded"


{-| The sentence under the row: what it is doing, or why it stopped.

A failed job's `error` is the only record of what went wrong that exists
anywhere — the manager keeps fifty terminal jobs and none across a restart — so
it is shown rather than summarised.

A waiting job usually has no message at all, and the sentence it gets instead is
the fact that makes this screen worth opening: there is one worker, so it is not
slow, it has not started.
-}
detailFor : Api.Job -> String
detailFor aJob =
    case aJob.status of
        Api.Failed detail ->
            detail

        Api.Queued ->
            if String.isEmpty aJob.message then
                "Waiting for the worker — one job runs at a time, so everything "
                    ++ "above this has to finish first."

            else
                aJob.message

        _ ->
            aJob.message



-- VIEW


type alias Config msg =
    { state : State
    , songs : List Api.Song
    , problem : Maybe String
    , onCancel : String -> msg
    , onBack : msg
    }


view : Config msg -> Html msg
view config =
    div [ class "queue" ]
        -- "Back" rather than a destination, as on the renders screen: closing
        -- this returns you to wherever you opened it from.
        [ button [ class "back", onClick config.onBack ] [ text "← Back" ]
        , h2 [] [ text "Queue" ]
        , p [ class "dim" ] [ text liveOnlyNote ]
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
            p [ class "dim" ] [ text "Loading what is running…" ]

        Failed reason ->
            p [ class "error" ] [ text ("Could not load the queue — " ++ reason) ]

        Loaded jobs ->
            rows config jobs

        Stale jobs reason ->
            div []
                [ p [ class "error" ] [ text (staleNote reason) ]
                , rows config jobs
                ]


rows : Config msg -> List Api.Job -> Html msg
rows config jobs =
    case emptyNote jobs of
        Just words ->
            p [ class "dim" ] [ text words ]

        Nothing ->
            div [ class "queue-list" ] (List.map (row config) (ordered jobs))


row : Config msg -> Api.Job -> Html msg
row config aJob =
    div [ class "queue-row" ]
        (div [ class "queue-head" ]
            [ span [ class "queue-kind" ] [ text (kindLabel aJob.kind) ]
            , span [ class "queue-title" ] [ text (subject config.songs aJob) ]
            , span (statusClass aJob.status) [ text (statusLabel aJob.status) ]
            , span [ class "queue-when" ] [ text (Renders.momentOf aJob.createdAt) ]
            ]
            :: progress aJob
            ++ [ actions config aJob ]
        )


{-| Two whole class strings rather than one assembled from pieces — see
`Page.Mixer.soloClass` for why, and `tests/test_static_bundle.py` for what
enforces it.

`queue-bad` rather than the page's existing `.error` for the same reason
`.render-bad` exists, and with the same correction: the stylesheet writes
`.queue .queue-status` (0-2-0) and `.error` is 0-1-0, so `.error` on a status
span loses on **specificity** wherever it is stated. Order has nothing to do
with it; a failed job would read in the grey of a waiting one however the file
were arranged.
-}
statusClass : Api.JobStatus -> List (Attribute msg)
statusClass status =
    case status of
        Api.Failed _ ->
            [ class "queue-status queue-bad" ]

        Api.Cancelled ->
            [ class "queue-status queue-bad" ]

        _ ->
            [ class "queue-status" ]


{-| A bar for the job that is actually moving, and for no other.

**The two kinds of job mean very different things by this bar, and only one of
them moves.** A render's fraction is real: `pipeline.run_pipeline` reports
through its stage checkpoints and `progress.Reporter` clamps and monotonises
it, so the bar advances as the mix is built. A separation's does not.
`separation_worker._phase` emits three hard-coded fractions — 0.05, 0.15,
0.90 — and `_demucs_separate` calls `apply_model` with `progress=False`, so
everything between "Separating stems" and "Writing stems" is one opaque call.
The bar reaches 15% in the first second or two and stays there for the whole
run, which is the several minutes anyone is actually waiting through.

Drawn anyway, and deliberately: this is the screen where the operator decides
whether to cancel, and a still bar next to a "running" status is at least
honest about there being nothing to say. What would not be honest is claiming
it means more than it does — see `docs/project-state.md` for what making a
separation's bar move would cost.

A queued job's `fraction` is 0.0 and
will stay there until the worker reaches it, and an empty track next to the word
"waiting" would be a bar that says nothing twice; the sentence under the row
says the useful thing instead. A terminal job has nowhere left to get to.
-}
progress : Api.Job -> List (Html msg)
progress aJob =
    case aJob.status of
        Api.Running ->
            [ div [ class "progress" ]
                [ div [ class "progress-track" ]
                    [ div
                        [ class "progress-fill"
                        , Attr.style "width" (String.fromFloat (aJob.fraction * 100) ++ "%")
                        ]
                        []
                    ]
                , span [ class "dim" ]
                    [ text (String.fromInt (round (aJob.fraction * 100)) ++ "%") ]
                ]
            ]

        _ ->
            []


{-| The cancel button, and the sentence beside it.

The button is absent rather than disabled on a job that has ended: there is
nothing to stop, and a greyed-out control implies there is something that could
be re-enabled. `cancellable` decides, so the same question the server answers is
asked in one place here.
-}
actions : Config msg -> Api.Job -> Html msg
actions config aJob =
    div [ class "queue-actions" ]
        ((if cancellable aJob then
            [ button [ class "cancel", onClick (config.onCancel aJob.id) ]
                [ text "Cancel" ]
            ]

          else
            []
         )
            ++ [ span [ class "dim" ] [ text (detailFor aJob) ] ]
        )
