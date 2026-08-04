port module Main exposing
    ( JobOutcome(..)
    , Model
    , Msg(..)
    , SelectOutcome
    , Separation(..)
    , Settings(..)
    , StreamFailure(..)
    , init
    , isSeparating
    , jobOutcome
    , main
    , separationOnSelect
    , streamFailureFor
    , update
    )

{-| The sleepmix interface.

Elm rather than a JavaScript framework because most of this is written by an
agent, and the compiler turns a whole class of mistakes — a renamed field, an
unhandled case — into build failures rather than into something that renders
blank and says nothing.

Where Elm stops: ports are asynchronous and JSON-only, so the Web Audio engine
and the EventSource connection live in hand-written JavaScript. Elm sends
parameters out and receives outcomes back; it never touches audio bytes.
-}

import Api
import Browser
import Config
import Html exposing (Html, div, h1, p, text)
import Html.Attributes exposing (class)
import Http
import Json.Decode as Decode
import Json.Encode as Encode
import Page.Library as Library
import Page.Mixer as Mixer
import Page.Song
import Preview
import Request
import Schema


{-| Elm cannot open an `EventSource` — `elm/http` has no server-sent-events
support — so `ui/ports/events.js` owns the connection and forwards parsed
events in. A job id goes out; a decoded JSON value comes back.
-}
port watchJob : String -> Cmd msg


port stopWatchingJob : String -> Cmd msg


port jobEvent : (Decode.Value -> msg) -> Sub msg


{-| The stream died without ever reporting a terminal status.

A dedicated port rather than an error envelope over `jobEvent`: `jobEvent`
carries exactly one thing, a job, decoded by exactly one strict decoder, and
an envelope would turn that decoder into a union whose failure mode ("this
isn't an error, so it must be a job") is precisely the permissiveness
`Api.elm` exists to refuse. A second port costs one line in `events.js` and
keeps both channels single-purpose.

The browser cannot tell a terminal close from a network blip, a server
restart, or a 404 for an unknown job — so `events.js` reports every one of
them and Elm, which knows whether it already saw a terminal event, decides
whether this was expected. See `streamFailureFor`.
-}
port jobStreamFailed : (String -> msg) -> Sub msg


{-| Preview playback, in `ui/ports/audio.js`.

Elm never sees a sample. `requestPreview` carries the parameters — always
`Preview.encode`'s output, never a `Params` record, whose Elm field names the
API would reject — and `audio.js` fetches `/api/preview` itself, decodes the
WAV, and swaps it in at the next loop boundary.

Exactly one reply per request is the contract this side depends on: `audio.js`
answers every request it starts with `previewReady` or `previewFailed` unless
`stopPreview` has told it to forget the request, and `Preview.arrived` is
called once for each of those. A reply Elm did not cause would advance the
state machine past a request that is still in flight; a request with no reply
would leave it in `InFlight` forever, and the scrubber would stop responding
with nothing on screen to say why.

`previewReady` takes a `Decode.Value` and not `()` for a reason worth writing
down: `audio.js` sends `{ durationS }`, and a `()` port compiles to
`Json.Decode.null`, which rejects an object at runtime with a port error the
Elm side cannot see or handle. The screen would sit at "Preparing…" forever
while the audio played underneath it. The payload is the length of the loop
that is now playing, which the mixer shows.
-}
port requestPreview : Encode.Value -> Cmd msg


port stopPreview : () -> Cmd msg


port previewReady : (Decode.Value -> msg) -> Sub msg


port previewFailed : (String -> msg) -> Sub msg


{-| What is happening to the separation of the song on screen.

One union rather than a `separating : Bool` beside a `trackedJob : Maybe Job`,
because that pair could express "a job is running for this song, but we aren't
watching it" — a state the view rendered as a live button reading
"Separating…", which POSTed a second job onto a single-worker queue when
clicked. `Page.Library.State` makes the same argument for its own shape.

`Starting` carries the request that will answer it and the song it was issued
for: the first so a superseded POST's response can be recognised and dropped
(see `Separated`), the second so re-entering the same song can keep watching
rather than orphan the job (see `separationOnSelect`).
-}
type Separation
    = Idle
    | Starting { request : Int, songId : String }
    | Watching Api.Job


isSeparating : Separation -> Bool
isSeparating separation =
    case separation of
        Idle ->
            False

        Starting _ ->
            True

        Watching _ ->
            True


{-| Which song a separation belongs to, if it belongs to one at all.
-}
separationSongId : Separation -> Maybe String
separationSongId separation =
    case separation of
        Idle ->
            Nothing

        Starting pending ->
            Just pending.songId

        Watching job ->
            job.songId


{-| The job whose `EventSource` we currently own, if any. Anything discarding a
separation has to close that stream, or it stays open in `events.js`'s map with
nothing on the Elm side listening to it.
-}
watchedJobId : Separation -> Maybe String
watchedJobId separation =
    case separation of
        Watching job ->
            Just job.id

        _ ->
            Nothing


{-| The config schema, which every control in the mixer is generated from.

Fetched once at startup rather than on entering the mixer: it is the same
answer for the life of the process, and asking for it while someone is waiting
on a preview would be one more thing between them and hearing something. A
union rather than a `Maybe` beside an error string, for the reason `Separation`
gives at length — the fourth combination is unrepresentable this way.
-}
type Settings
    = SettingsLoading
    | SettingsReady Schema.Schema
    | SettingsUnavailable String


type alias Model =
    { health : Health
    , library : Library.State
    , pathInput : String
    , importing : Bool
    , importError : Maybe String
    , selectedSongId : Maybe String
    , currentSong : Maybe Api.Song
    , songError : Maybe String
    , peaks : List ( Float, Float )
    , peaksError : Maybe String
    , loop : Maybe Api.LoopRegion
    , loopError : Maybe String
    , settings : Settings
    , mixer : Maybe Mixer.State
    , preview : Preview.State
    , previewError : Maybe String
    , loopSeconds : Maybe Float
    , separation : Separation
    , separateError : Maybe String
    , eventError : Maybe String
    , songRequest : Int
    , peaksRequest : Int
    , loopRequest : Int
    , nextRequest : Int
    }


{-| A monotonic id per issued request, rather than the song id the request was
for. A song id answers "is this response still for the song on screen", which
lets a stale response through when the answer is yes for the wrong reason: a
fast A → B → A leaves the first A request in flight while `selectedSongId`
reads `Just "A"` again, so whichever response lands second wins even when it is
the older one. A counter has no such collision.
-}
issue : Model -> ( Int, Model )
issue model =
    ( model.nextRequest, { model | nextRequest = model.nextRequest + 1 } )


{-| What an incoming job event means, given what we are currently watching.
-}
type JobOutcome
    = Ignored
    | Tracking Api.Job
    | Finished Api.Job


{-| Pure and returning a value rather than a `Cmd`, so it can be tested. Events
for other jobs are ignored rather than adopted: two jobs can be in flight, and
the stream for one must not hijack the progress bar of the other.
-}
jobOutcome : Api.Job -> Separation -> JobOutcome
jobOutcome incoming separation =
    case separation of
        Watching current ->
            if incoming.id /= current.id then
                Ignored

            else if Api.isFinished incoming.status then
                Finished incoming

            else
                Tracking incoming

        _ ->
            Ignored


type StreamFailure
    = StreamIrrelevant
    | StreamLost String


{-| A stream closing only matters while we are still waiting on that job.

`update` sets `Idle` and sends `stopWatchingJob` the moment a terminal event
lands, and `events.js` reports nothing for a stream it has already been told to
drop — so by the time a genuine terminal close reaches here there is nothing
left to be lost, and this reads `StreamIrrelevant`.
-}
streamFailureFor : String -> Separation -> StreamFailure
streamFailureFor jobId separation =
    case separation of
        Watching job ->
            if job.id == jobId then
                StreamLost jobId

            else
                StreamIrrelevant

        _ ->
            StreamIrrelevant


type alias SelectOutcome =
    { separation : Separation
    , stopWatching : Maybe String
    }


{-| What a separation should become when a song is opened.

Kept, if it belongs to the song being opened — leaving the library and coming
back used to reset tracking to nothing, after which every event including the
terminal one was discarded, the stream was never closed, and the panel said
"Separating…" until a manual reload. Discarded otherwise, and the job id it was
watching comes back so the caller can close that stream rather than leave it
open and unowned.
-}
separationOnSelect : String -> Separation -> SelectOutcome
separationOnSelect songId separation =
    if separationSongId separation == Just songId then
        { separation = separation, stopWatching = Nothing }

    else
        { separation = Idle, stopWatching = watchedJobId separation }


{-| Which screen is showing.

Not stored in the model directly — it is derived from `selectedSongId` and
`mixer` by `routeFor`, so there is exactly one source of truth for "which song,
if any, is open" and one for "is the mixer open on it", rather than a separate
field that could disagree with either.

The mixer's own state *is* the mixer being open: it exists only while the
screen does, and `leaveMixer` throws it away and stops the audio in the same
step. There is no way to be on the mixer with nothing to mix, and no way to
leave it while a preview keeps looping underneath the library.
-}
type Route
    = Library
    | SongView String
    | MixerView Mixer.State


routeFor : Model -> Route
routeFor model =
    case model.mixer of
        Just state ->
            MixerView state

        Nothing ->
            case model.selectedSongId of
                Nothing ->
                    Library

                Just songId ->
                    SongView songId


{-| How many peak buckets to ask for. 200 buckets across the 960px-wide
waveform in `Page.Song` gives a bar every ~4.8px, dense enough to show shape
without asking the server to compute (and the browser to draw) more detail
than a screen can show.
-}
peakBuckets : Int
peakBuckets =
    200


type Health
    = Checking
    | Ready String
    | Unreachable String


type Msg
    = GotHealth (Result Http.Error String)
    | GotSongs (Result Http.Error (List Api.Song))
    | GotSchema (Result Http.Error Schema.Schema)
    | PathChanged String
    | ImportClicked
    | Imported (Result Http.Error Api.Song)
    | SelectedSong String
    | BackToLibrary
    | GotSongDetail Int (Result Http.Error Api.Song)
    | GotPeaks Int (Result Http.Error (List ( Float, Float )))
    | GotLoop Int (Result Http.Error Api.LoopRegion)
    | SeparateClicked Bool
    | Separated Int (Result Http.Error Api.Job)
    | JobEventReceived (Result Decode.Error Api.Job)
    | JobStreamFailed String
    | OpenMixer
    | CloseMixer
    | ProgressChanged String
    | SoloToggled String
    | FieldChanged Config.Target String
    | FieldToggled Config.Target Bool
    | RetryPreview
    | PreviewPlaying (Maybe Float)
    | PreviewFailed String


main : Program () Model Msg
main =
    Browser.element
        { init = init
        , update = update
        , subscriptions = subscriptions
        , view = view
        }


{-| A malformed event surfaces as a `Result` for `update` to handle rather
than crashing the application.
-}
subscriptions : Model -> Sub Msg
subscriptions _ =
    Sub.batch
        [ jobEvent (Decode.decodeValue Api.job >> JobEventReceived)
        , jobStreamFailed JobStreamFailed
        , previewReady (playingLoopSeconds >> PreviewPlaying)
        , previewFailed PreviewFailed
        ]


{-| How long the loop that just started playing is.

Read leniently, and deliberately: this is a readout, not a decision. A payload
this build does not understand costs a line of text, where the strictness
`Api.elm` argues for would cost the whole mixer — the preview *is* playing by
the time this arrives, and refusing to acknowledge it would strand the state
machine in `InFlight` with audio in the room.
-}
playingLoopSeconds : Decode.Value -> Maybe Float
playingLoopSeconds value =
    Decode.decodeValue (Decode.field "durationS" Decode.float) value
        |> Result.toMaybe


init : () -> ( Model, Cmd Msg )
init _ =
    ( { health = Checking
      , library = Library.Loading
      , pathInput = ""
      , importing = False
      , importError = Nothing
      , selectedSongId = Nothing
      , currentSong = Nothing
      , songError = Nothing
      , peaks = []
      , peaksError = Nothing
      , loop = Nothing
      , loopError = Nothing
      , settings = SettingsLoading
      , mixer = Nothing
      , preview = Preview.Cold
      , previewError = Nothing
      , loopSeconds = Nothing
      , separation = Idle
      , separateError = Nothing
      , eventError = Nothing
      , songRequest = 0
      , peaksRequest = 0
      , loopRequest = 0
      , nextRequest = 1
      }
    , Cmd.batch
        [ Http.get
            { url = "/api/health"
            , expect = Http.expectJson GotHealth (Decode.field "version" Decode.string)
            }
        , Request.songs GotSongs
        , Request.schema GotSchema
        ]
    )


{-| Appended to anything that loses contact with a running separation. The job
is on the server's single worker and keeps going whatever this screen believes;
saying so is the difference between an error someone can act on and one that
just reads as breakage.
-}
stillRunningNote : String
stillRunningNote =
    " It may still be running — reload to see where it got to."


update : Msg -> Model -> ( Model, Cmd Msg )
update msg model =
    case msg of
        GotHealth (Ok version) ->
            ( { model | health = Ready version }, Cmd.none )

        GotHealth (Err err) ->
            ( { model | health = Unreachable (httpErrorToString err) }, Cmd.none )

        GotSongs (Ok songs) ->
            ( { model | library = Library.Loaded songs }, Cmd.none )

        GotSongs (Err err) ->
            ( { model | library = Library.Failed (httpErrorToString err) }, Cmd.none )

        GotSchema (Ok schema) ->
            ( { model | settings = SettingsReady schema }, Cmd.none )

        GotSchema (Err err) ->
            ( { model | settings = SettingsUnavailable (httpErrorToString err) }, Cmd.none )

        PathChanged path ->
            ( { model | pathInput = path }, Cmd.none )

        ImportClicked ->
            if model.importing || String.isEmpty model.pathInput then
                ( model, Cmd.none )

            else
                ( { model | importing = True, importError = Nothing }
                , Request.importSong model.pathInput Imported
                )

        Imported (Ok _) ->
            -- Re-fetch rather than append the returned song: the server
            -- deduplicates by path, so importing a file that is already in
            -- the library returns the existing row, and appending it here
            -- would show that song twice.
            ( { model | importing = False, pathInput = "" }
            , Request.songs GotSongs
            )

        Imported (Err err) ->
            ( { model | importing = False, importError = Just (httpErrorToString err) }
            , Cmd.none
            )

        SelectedSong songId ->
            -- Entering a song resets everything the previous one left behind
            -- (peaks, errors) so stale state from one song can never bleed
            -- into the next. A separation is the one exception: if it belongs
            -- to *this* song it is kept, because dropping it would orphan the
            -- job and strand the panel at "Separating…" forever.
            let
                outcome =
                    separationOnSelect songId model.separation

                ( songRequest, withSong ) =
                    issue model

                ( peaksRequest, withPeaks ) =
                    issue withSong

                ( loopRequest, issued ) =
                    issue withPeaks

                ( closed, stopped ) =
                    leaveMixer issued
            in
            ( { closed
                | selectedSongId = Just songId
                , currentSong = Nothing
                , songError = Nothing
                , peaks = []
                , peaksError = Nothing
                , loop = Nothing
                , loopError = Nothing
                , separation = outcome.separation
                , separateError = Nothing
                , eventError = Nothing
                , songRequest = songRequest
                , peaksRequest = peaksRequest
                , loopRequest = loopRequest
              }
            , Cmd.batch
                [ Request.song songId (GotSongDetail songRequest)
                , Request.peaks songId peakBuckets (GotPeaks peaksRequest)
                , Request.loop songId noOverride (GotLoop loopRequest)
                , stopWatching outcome.stopWatching
                , stopped
                ]
            )

        BackToLibrary ->
            -- The separation is deliberately left alone. It is still running,
            -- its stream is still ours, and re-entering the song picks it back
            -- up; a terminal event arriving while the library is on screen
            -- re-fetches the list instead of the song (see `Finished`).
            --
            -- A preview is not left alone: it loops forever by design, so
            -- walking away from the mixer without stopping it leaves music
            -- playing under the library with nothing on screen to stop it.
            let
                ( closed, stopped ) =
                    leaveMixer model
            in
            ( { closed | selectedSongId = Nothing }, stopped )

        GotSongDetail request result ->
            -- Guard against a slow response landing after the user has moved
            -- on, or after a newer request for this same song was issued.
            if model.songRequest /= request then
                ( model, Cmd.none )

            else
                case result of
                    Ok song ->
                        ( { model | currentSong = Just song, songError = Nothing }, Cmd.none )

                    Err err ->
                        ( { model | songError = Just (httpErrorToString err) }, Cmd.none )

        GotPeaks request result ->
            if model.peaksRequest /= request then
                ( model, Cmd.none )

            else
                case result of
                    Ok peaks ->
                        ( { model | peaks = peaks, peaksError = Nothing }, Cmd.none )

                    Err err ->
                        ( { model | peaksError = Just (httpErrorToString err) }, Cmd.none )

        GotLoop request result ->
            if model.loopRequest /= request then
                ( model, Cmd.none )

            else
                case result of
                    Ok region ->
                        ( { model | loop = Just region, loopError = Nothing }, Cmd.none )

                    Err err ->
                        ( { model | loopError = Just (httpErrorToString err) }, Cmd.none )

        SeparateClicked force ->
            case model.selectedSongId of
                Nothing ->
                    ( model, Cmd.none )

                Just songId ->
                    if isSeparating model.separation then
                        -- The button is disabled while a separation is in
                        -- flight; the model does not rely on that being true.
                        ( model, Cmd.none )

                    else
                        let
                            ( request, issued ) =
                                issue model
                        in
                        ( { issued
                            | separation = Starting { request = request, songId = songId }
                            , separateError = Nothing
                            , eventError = Nothing
                          }
                        , Request.startSeparation songId force (Separated request)
                        )

        Separated request result ->
            case model.separation of
                Starting pending ->
                    if pending.request /= request then
                        -- A POST we have since abandoned. Adopting it would
                        -- start watching a job for a song that is no longer on
                        -- screen, and re-fetch the wrong song when it finished.
                        ( model, Cmd.none )

                    else
                        case result of
                            Ok job ->
                                -- Don't re-fetch yet: the job has only just
                                -- been queued, and its progress from here on
                                -- comes from the event stream, not from
                                -- polling the song.
                                ( { model | separation = Watching job }, watchJob job.id )

                            Err err ->
                                ( { model
                                    | separation = Idle
                                    , separateError = Just (httpErrorToString err)
                                  }
                                , Cmd.none
                                )

                _ ->
                    ( model, Cmd.none )

        JobEventReceived (Ok incoming) ->
            case jobOutcome incoming model.separation of
                Ignored ->
                    ( model, Cmd.none )

                Tracking job ->
                    ( { model | separation = Watching job }, Cmd.none )

                Finished job ->
                    -- Re-fetch rather than trust the job's own fields: the
                    -- job reports its own progress, not the song's
                    -- separation_status, and that status is what the panel
                    -- and the button label read from.
                    let
                        ( refetched, refetch ) =
                            refetchAfter job model
                    in
                    ( { refetched | separation = Idle }
                    , Cmd.batch [ stopWatchingJob job.id, refetch ]
                    )

        JobEventReceived (Err decodeErr) ->
            -- Separation started fine; the *event* was unreadable. Its own
            -- field and its own wording, and a clean exit: leaving
            -- `separation` alone here is what used to hang the panel at
            -- "Separating…" with a JSON path dump above it saying separation
            -- had failed to start.
            ( { model
                | separation = Idle
                , eventError =
                    Just
                        ("Lost track of the separation — a progress event could not be read: "
                            ++ Decode.errorToString decodeErr
                            ++ "."
                            ++ stillRunningNote
                        )
              }
            , stopWatching (watchedJobId model.separation)
            )

        JobStreamFailed jobId ->
            case streamFailureFor jobId model.separation of
                StreamIrrelevant ->
                    ( model, Cmd.none )

                StreamLost _ ->
                    -- `events.js` has already closed and forgotten this
                    -- connection, so there is nothing to stop watching.
                    ( { model
                        | separation = Idle
                        , eventError =
                            Just
                                ("Lost track of the separation — the progress stream closed before it reported finishing."
                                    ++ stillRunningNote
                                )
                      }
                    , Cmd.none
                    )

        OpenMixer ->
            case ( model.currentSong, model.settings ) of
                ( Just song, SettingsReady schema ) ->
                    if List.isEmpty song.stems || separatingNow song model then
                        -- Both halves of `Page.Song.mixerPanel`'s gate, because
                        -- the model does not rely on a button being disabled.
                        -- No stems: the first preview would run Demucs inside
                        -- the preview lock with nothing reporting progress.
                        -- Mid-separation: finishing discards the warm session
                        -- and can change the stem list under an open mixer.
                        ( model, Cmd.none )

                    else
                        let
                            state =
                                Mixer.init song.id schema song.stems

                            -- One preview at progress 0, which is also what
                            -- `master_gain` calibrates from: until it returns
                            -- there is no level to play anything at, so every
                            -- control on the screen is inert and says so.
                            ( preview, toSend ) =
                                Preview.warm (Mixer.params state) model.preview
                        in
                        ( { model
                            | mixer = Just state
                            , preview = preview
                            , previewError = Nothing
                            , loopSeconds = Nothing
                          }
                        , sendPreview toSend
                        )

                _ ->
                    ( model, Cmd.none )

        CloseMixer ->
            leaveMixer model

        ProgressChanged raw ->
            withMixer (Mixer.setProgress raw) model

        SoloToggled name ->
            withMixer (Mixer.toggleSolo name) model

        FieldToggled target on ->
            withMixer (Mixer.toggleField target on) model

        FieldChanged target raw ->
            case model.settings of
                SettingsReady schema ->
                    withMixer (Mixer.setField schema target raw) model
                        |> andThen (refetchLoopFor target)

                _ ->
                    ( model, Cmd.none )

        RetryPreview ->
            -- The same parameters again, through whichever door fits the state
            -- the failure left behind — `Preview.retry` decides which, exactly
            -- as `Preview.request` decides for a control change.
            case model.mixer of
                Nothing ->
                    ( model, Cmd.none )

                Just state ->
                    let
                        ( preview, toSend ) =
                            Preview.retry (Mixer.params state) model.preview
                    in
                    ( { model | preview = preview, previewError = Nothing }
                    , sendPreview toSend
                    )

        PreviewPlaying seconds ->
            let
                ( preview, toSend ) =
                    Preview.arrived (Preview.warmed model.preview)
            in
            ( { model
                | preview = preview
                , previewError = Nothing
                , loopSeconds = seconds
              }
            , sendPreview toSend
            )

        PreviewFailed reason ->
            -- Not the same transition as a success. An opening preview that
            -- never came back leaves nothing known to be playable, and
            -- `Preview.failed` says so by going back to `Cold` rather than
            -- opening the controls over silence.
            let
                ( preview, toSend ) =
                    Preview.failed model.preview
            in
            ( { model
                | preview = preview
                , previewError = Just reason
                , loopSeconds = Nothing
              }
            , sendPreview toSend
            )


{-| What to re-fetch once a job reaches a terminal status.

The song, if that job's song is the one on screen. The library list otherwise —
a separation started and then left behind still changes the row it came from,
and a list showing "not separated" for a song that has just been separated is
the same staleness one level up.
-}
refetchAfter : Api.Job -> Model -> ( Model, Cmd Msg )
refetchAfter job model =
    case job.songId of
        Just jobSongId ->
            if model.selectedSongId == Just jobSongId then
                let
                    ( request, issued ) =
                        issue model
                in
                ( { issued | songRequest = request }
                , Request.song jobSongId (GotSongDetail request)
                )

            else
                ( model, Request.songs GotSongs )

        Nothing ->
            ( model, Request.songs GotSongs )


{-| Is this song separating right now, by either account?

The client's own flag, and the server's status for the case the flag cannot
cover: a reload mid-separation forgets that a job was started but the row still
says `running`.
-}
separatingNow : Api.Song -> Model -> Bool
separatingNow song model =
    isSeparating model.separation || song.separationStatus == Api.Separating


{-| Ask the loop endpoint to detect a region rather than echo one back.
-}
noOverride : { startS : Maybe Float, endS : Maybe Float }
noOverride =
    { startS = Nothing, endS = Nothing }


{-| Run a second step over the result of a first, keeping both commands.
-}
andThen : (Model -> ( Model, Cmd Msg )) -> ( Model, Cmd Msg ) -> ( Model, Cmd Msg )
andThen next ( model, cmd ) =
    let
        ( updated, more ) =
            next model
    in
    ( updated, Cmd.batch [ cmd, more ] )


{-| Every change the mixer can make, in one place.

Note what is *not* here: any test of whether a request should go out. The
scrubber emits a message per pixel of drag and each one arrives here; which of
them reaches the server is `Preview.request`'s decision alone, and this passes
on whatever it hands back. A condition of the form "only if nothing is in
flight" written here would be the same logic in a place `elm-test` cannot
reach, which is the whole argument for `Preview.elm` existing.
-}
withMixer : (Mixer.State -> Mixer.State) -> Model -> ( Model, Cmd Msg )
withMixer change model =
    case model.mixer of
        Nothing ->
            ( model, Cmd.none )

        Just state ->
            let
                updated =
                    change state

                ( preview, toSend ) =
                    Preview.request (Mixer.params updated) model.preview
            in
            ( { model | mixer = Just updated, preview = preview }, sendPreview toSend )


sendPreview : Maybe Preview.Params -> Cmd msg
sendPreview toSend =
    case toSend of
        Just params ->
            -- `Preview.encode`, never the record: the API's keys are Python's
            -- and the record's are Elm's, and the mismatch is a 422 on every
            -- preview rather than a compile error.
            requestPreview (Preview.encode params)

        Nothing ->
            Cmd.none


{-| Leaving the mixer, by whichever door.

Closing it, opening another song, and going back to the library all come
through here, because a preview loops until something stops it and only one of
those three is the obvious one to remember.
-}
leaveMixer : Model -> ( Model, Cmd Msg )
leaveMixer model =
    case model.mixer of
        Nothing ->
            ( model, Cmd.none )

        Just _ ->
            ( { model
                | mixer = Nothing
                , preview = Preview.Cold
                , previewError = Nothing
                , loopSeconds = Nothing
              }
            , stopPreview ()
            )


{-| Keep the region drawn on the waveform honest about what a render would
loop.

Only for the two fields the endpoint can actually take. `bars`, `beats_per_bar`
and the search window are config fields a render honours and `GET
/api/songs/{id}/loop` has no parameter for, so re-asking after one of those
changed would redraw the same region and charge a full beat-tracking pass for
it — the call decodes the whole file every time and caches nothing.
-}
refetchLoopFor : Config.Target -> Model -> ( Model, Cmd Msg )
refetchLoopFor target model =
    case ( isLoopRegion target, model.selectedSongId, model.mixer ) of
        ( True, Just songId, Just state ) ->
            let
                ( request, issued ) =
                    issue model
            in
            ( { issued | loopRequest = request }
            , Request.loop songId (Mixer.loopOverride state) (GotLoop request)
            )

        _ ->
            ( model, Cmd.none )


isLoopRegion : Config.Target -> Bool
isLoopRegion target =
    case target of
        Config.InSection "loop" key ->
            key == "start_s" || key == "end_s"

        _ ->
            False


stopWatching : Maybe String -> Cmd msg
stopWatching jobId =
    case jobId of
        Just id ->
            stopWatchingJob id

        Nothing ->
            Cmd.none


httpErrorToString : Http.Error -> String
httpErrorToString err =
    case err of
        Http.BadUrl url ->
            "bad url: " ++ url

        Http.Timeout ->
            "the server took too long to answer"

        Http.NetworkError ->
            "could not reach the server"

        Http.BadStatus code ->
            "the server answered " ++ String.fromInt code

        Http.BadBody detail ->
            "could not read the server's answer: " ++ detail


view : Model -> Html Msg
view model =
    div [ class "app" ]
        [ h1 [] [ text "sleepmix" ]
        , case model.health of
            Checking ->
                p [] [ text "Connecting…" ]

            Ready version ->
                p [ class "dim" ] [ text ("Connected to sleepmix " ++ version ++ ".") ]

            Unreachable reason ->
                p [ class "error" ] [ text ("Not connected — " ++ reason) ]
        , case routeFor model of
            Library ->
                libraryView model

            SongView songId ->
                songView model songId

            MixerView state ->
                mixerView model state
        ]


libraryView : Model -> Html Msg
libraryView model =
    div []
        [ Library.view
            { state = model.library
            , pathInput = model.pathInput
            , importing = model.importing
            , onPathInput = PathChanged
            , onImport = ImportClicked
            , onSelect = SelectedSong
            }
        , errorLine (\reason -> "Could not import that file — " ++ reason) model.importError
        ]


errorLine : (String -> String) -> Maybe String -> Html msg
errorLine phrase reason =
    case reason of
        Nothing ->
            text ""

        Just detail ->
            p [ class "error" ] [ text (phrase detail) ]


{-| The tracked job's progress, but only when it belongs to the song on
screen — a job for a song the user has since navigated away from and back to
must not paint a stale bar here.
-}
progressFor : String -> Model -> Maybe Float
progressFor songId model =
    case model.separation of
        Watching job ->
            if job.songId == Just songId then
                Just job.fraction

            else
                Nothing

        _ ->
            Nothing


{-| The song screen. `currentSong` is `Nothing` until its fetch lands — until
then this shows a loading line rather than the page, since `Page.Song.view`
needs a real `Api.Song` to read a title and duration from.

Every error the song screen can hold is rendered here, including `songError`,
which the post-separation re-fetch can set while a song is already on screen.
It used to be reachable only in the `Nothing` branch, so a failed re-fetch was
written to the model and never shown while the panel kept displaying the
pre-separation status.
-}
songView : Model -> String -> Html Msg
songView model songId =
    div []
        [ case model.currentSong of
            Nothing ->
                if model.songError == Nothing then
                    p [ class "dim" ] [ text "Loading song…" ]

                else
                    text ""

            Just song ->
                Page.Song.view
                    { song = song
                    , peaks = model.peaks
                    , loop = model.loop
                    , separating = isSeparating model.separation
                    , progress = progressFor songId model
                    , onSeparate = SeparateClicked
                    , onMixer = OpenMixer
                    , onBack = BackToLibrary
                    }
        , errorLine (\reason -> "Could not load that song — " ++ reason) model.songError
        , errorLine (\reason -> "Could not load the waveform — " ++ reason) model.peaksError
        , errorLine (\reason -> "Could not find the loop — " ++ reason) model.loopError
        , errorLine (\reason -> "Could not start separation — " ++ reason) model.separateError
        , errorLine identity model.eventError
        , settingsProblem model.settings
        ]


{-| The mixer needs two things this screen does not: the song it is mixing, and
the schema its controls are generated from. Neither can be missing by the time
`OpenMixer` has been handled — it refuses to open without them — so this is
belt and braces rather than a state anyone should reach.
-}
mixerView : Model -> Mixer.State -> Html Msg
mixerView model state =
    case ( model.currentSong, model.settings ) of
        ( Just song, SettingsReady schema ) ->
            div []
                [ Mixer.view
                    { state = state
                    , song = song
                    , schema = schema
                    , peaks = model.peaks
                    , loop = model.loop
                    , preview = model.preview
                    , previewError = model.previewError
                    , loopSeconds = model.loopSeconds
                    , onBack = CloseMixer
                    , onProgress = ProgressChanged
                    , onSolo = SoloToggled
                    , onField = FieldChanged
                    , onToggle = FieldToggled
                    , onRetry = RetryPreview
                    }
                , errorLine (\reason -> "Could not find the loop — " ++ reason) model.loopError
                ]

        _ ->
            p [ class "dim" ] [ text "Loading the mixer…" ]


{-| A schema that never arrived is not a detail: every control in the mixer is
built out of it, so there is no mixer at all without one.
-}
settingsProblem : Settings -> Html msg
settingsProblem settings =
    case settings of
        SettingsUnavailable reason ->
            p [ class "error" ]
                [ text
                    ("Could not load the settings the mixer is built from — "
                        ++ reason
                        ++ ". The mixer will not open until that request succeeds."
                    )
                ]

        _ ->
            text ""
