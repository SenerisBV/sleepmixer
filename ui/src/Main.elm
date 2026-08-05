port module Main exposing
    ( BadEvent
    , Defaults(..)
    , JobOutcome(..)
    , Model
    , Msg(..)
    , PendingRender
    , SelectOutcome
    , Separation(..)
    , Settings(..)
    , StreamFailure(..)
    , init
    , isSeparating
    , jobOutcome
    , main
    , mixerOpenFor
    , readEvent
    , renderStartingFor
    , separationOnSelect
    , streamFailureFor
    , update
    , view
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
import Html exposing (Html, button, div, h1, p, text)
import Html.Attributes exposing (class)
import Html.Events exposing (onClick)
import Http
import Json.Decode as Decode
import Json.Encode as Encode
import Page.Library as Library
import Page.Mixer as Mixer
import Page.Queue as Queue
import Page.Renders as Renders
import Page.Song
import Preview
import Process
import Request
import Schema
import Task


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


{-| The server's own default `MixConfig`, which is what a mixer opens on.

Fetched once at startup beside the schema, and for the same reason: it is the
same answer for the life of the process, and asking for it when someone presses
"Open the mixer" would put a round trip between them and the screen.

A union rather than a `Maybe` beside an error string, exactly as `Settings` is.
The distinction that earns it is between "it has not answered yet" and "it
answered badly" — the mixer opens either way, so both are a fallback to the
schema's defaults, but only one of them has anything to say about why.

The schema and this are *not* interchangeable. `Schema` describes shapes and
this carries values; `Config.overlay` is what puts one over the other, with the
schema still deciding which keys may exist and what bounds they are held to.
-}
type Defaults
    = DefaultsLoading
    | DefaultsReady Decode.Value
    | DefaultsUnavailable String


{-| The published defaults, when there are any to open a mixer on.

Both non-ready states collapse to `Nothing` here, and `Page.Mixer.init` records
that the mixer opened without them so the screen can say so. A mixer that
refused to open until this arrived would turn one failed GET into a feature
nobody can reach.
-}
publishedDefaults : Defaults -> Maybe Decode.Value
publishedDefaults defaults =
    case defaults of
        DefaultsReady value ->
            Just value

        _ ->
            Nothing


{-| A render POST that has gone out and not yet been answered.

Carries the song it was issued for as well as the request that will answer it,
and the song half is not decoration — `Separation.Starting` carries one for
exactly the same reason, thirty lines up. Without it a POST in flight is a fact
about the *application* rather than about a song, and every consequence lands on
whichever song is open when the answer arrives: `renderBlock` greys out that
song's Render button under a sentence describing a different one, and the answer
then closes that song's mixer and stops its preview on the way to the renders
screen. With it, both questions — "is this button waiting?" and "should this
answer move the screen?" — are asked about a named song and answered no for
every other.

One at a time, deliberately. Pressing Render on a second song while the first is
in flight replaces this record, and the first answer is then dropped as
superseded: the render itself is running on the server either way, so what is
lost is the navigation, not the mix. A list would buy nothing — reaching the
second song's mixer takes a song fetch and a schema-driven screen, which is
orders of magnitude longer than the round trip this covers.
-}
type alias PendingRender =
    { request : Int
    , songId : String
    }


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
    , defaults : Defaults

    -- Every saved preset, and whatever the last thing the bar did has to say
    -- for itself. The list lives here rather than in `Mixer.State` because it
    -- outlives the screen and is the same for every song; the bar's own
    -- selection and name box do not, and are thrown away with the mixer.
    -- `presetProblem` is rendered by the bar and by nothing else, so
    -- `leaveMixer` clears it for the reason `renderError` is cleared there.
    , presets : List Api.Preset
    , presetProblem : Maybe String
    , mixer : Maybe Mixer.State
    , renders : Maybe Renders.State
    , renderJobs : List Api.Job
    , watchedRender : Maybe String
    , rendersProblem : Maybe String
    , queue : Maybe Queue.State
    , queueTick : Int
    , queueProblem : Maybe String
    , preview : Preview.State
    , previewError : Maybe String
    , loopSeconds : Maybe Float

    -- The render POST the mixer's button has in flight, and why the last one
    -- failed. See `PendingRender` for why it carries a song as well as a
    -- request id, and `renderError`'s two guards — `RenderStarted`'s write and
    -- `leaveMixer`'s clear — for why the message cannot outlive the screen that
    -- shows it.
    , startingRender : Maybe PendingRender
    , renderError : Maybe String
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


{-| Is a render POST in flight *for this song*, rather than for some other?

What the mixer's Render button reads to decide whether it is waiting. Asked of a
named song rather than of the model as a whole, because the answer differs
between two songs and a `startingRender /= Nothing` cannot say so — it greyed
out the button on every song a POST outlived.
-}
renderStartingFor : String -> Model -> Bool
renderStartingFor songId model =
    Maybe.map .songId model.startingRender == Just songId


{-| Is the mixer open, and open on this song?

Used to decide whether there is anybody to tell about a render that failed to
start. `renderError` is rendered by the mixer and by nothing else, so writing it
while no mixer is open — or while a *different* song's mixer is open — is not a
lost message but a worse one: it sits in the model until the next mixer opens
and then reports a failure that has nothing to do with the song on screen.
Clearing it in `leaveMixer` is not enough on its own, because the write can
happen after the leave; this is the half that makes it true rather than usually
true.
-}
mixerOpenFor : String -> Model -> Bool
mixerOpenFor songId model =
    Maybe.map .songId model.mixer == Just songId


{-| Which screen is showing.

Not stored in the model directly — it is derived from `selectedSongId` and
`mixer` by `routeFor`, so there is exactly one source of truth for "which song,
if any, is open" and one for "is the mixer open on it", rather than a separate
field that could disagree with either.

The mixer's own state *is* the mixer being open: it exists only while the
screen does, and `leaveMixer` throws it away and stops the audio in the same
step. There is no way to be on the mixer with nothing to mix, and no way to
leave it while a preview keeps looping underneath the library.

`renders` is the same argument again: the fetch behind the renders screen
exists only while that screen does, so `Nothing` *is* "the screen is closed"
and there is no way to be on it showing the list from the last time it was
open. Entering it goes through `leaveMixer`, so a preview cannot go on looping
underneath it either.

What is deliberately *not* thrown away when it closes is `renderJobs` and
`watchedRender`: a render keeps going whether or not anyone is looking at it,
and dropping the watch would orphan the event stream — the same mistake
`separationOnSelect` exists to prevent one screen along.

`queue` is `renders` again, one screen further along, and for the same reason:
the fetch behind the queue screen exists only while the screen does, so
`Nothing` *is* "the screen is closed". That is also what stops the poll — see
`QueueTick`, which asks this field whether to carry on. A `polling : Bool`
beside a list would allow "closed but still polling", which is the state the
timer must never be able to reach.
-}
type Route
    = Library
    | QueueView Queue.State
    | RendersView Renders.State
    | SongView String
    | MixerView Mixer.State


{-| The queue and the renders screens are checked before the rest because either
can be open over a selected song: both are reached from the library's nav strip,
and closing one puts you back where you were rather than at the library.

Their order relative to each other is deliberately not load-bearing. `OpenQueue`
closes the renders screen and `OpenRenders` closes this one, so they are never
both open — stated in `update` rather than left to whichever branch happens to
be read first here.
-}
routeFor : Model -> Route
routeFor model =
    case model.queue of
        Just state ->
            QueueView state

        Nothing ->
            case model.renders of
                Just state ->
                    RendersView state

                Nothing ->
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
    | JobEventReceived (Result BadEvent Api.Job)
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
    | RenderClicked
    | RenderStarted Int (Result Http.Error Api.Job)
    | OpenRenders
    | CloseRenders
    | GotRenders (Result Http.Error (List Api.Render))
    | GotRenderJobs (Result Http.Error (List Api.Job))
    | DeleteRenderClicked String
    | RenderDeleted (Result Http.Error ())
    | CancelRenderClicked String
    | RenderCancelSent (Result Http.Error Api.Cancellation)
    | OpenQueue
    | CloseQueue
    | QueueTick Int
    | GotQueueJobs (Result Http.Error (List Api.Job))
    | CancelJobClicked String
    | JobCancelSent (Result Http.Error Api.Cancellation)
    | GotPresets (Result Http.Error (List Api.Preset))
    | GotDefaultConfig (Result Http.Error Decode.Value)
    | PresetSelected String
    | PresetApplied String
    | PresetNameChanged String
    | SavePresetAs
    | PresetSaved String (Result Http.Error Api.Preset)
    | PresetPending (Maybe Mixer.Pending)
    | SaveOverConfirmed
    | PresetUpdated String (Result Http.Error Api.Preset)
    | DeletePresetConfirmed
    | PresetDeleted String (Result Http.Error ())
    | LastPresetSet String (Result Http.Error Api.Song)


main : Program () Model Msg
main =
    Browser.element
        { init = init
        , update = update
        , subscriptions = subscriptions
        , view = view
        }


{-| An event that arrived and could not be read as a job.

The id is decoded on its own and leniently, because it is the only thing in an
unreadable frame that says *which* stream sent it — and `jobEvent` is one
channel carrying every stream this application opens. Without it a malformed
frame was charged to the separation whatever its origin: a bad frame on a
render's stream reset a genuinely running separation to `Idle` and closed its
stream while Demucs carried on, and wrote its explanation to `eventError`,
which only the song screen renders. Someone watching the renders screen saw
nothing at all, and a progress bar that had simply stopped.

`detail` is already a string rather than a `Decode.Error`, so the boundary
between "JSON went wrong" and "something to say about it" is crossed once, at
the edge, where `Api.job` is.
-}
type alias BadEvent =
    { jobId : Maybe String
    , detail : String
    }


{-| One frame off `jobEvent`, strictly as a job or precisely as a failure.
-}
readEvent : Decode.Value -> Result BadEvent Api.Job
readEvent value =
    case Decode.decodeValue Api.job value of
        Ok job ->
            Ok job

        Err err ->
            Err
                { jobId =
                    Decode.decodeValue (Decode.field "id" Decode.string) value
                        |> Result.toMaybe
                , detail = Decode.errorToString err
                }


{-| A malformed event surfaces as a `Result` for `update` to handle rather
than crashing the application.
-}
subscriptions : Model -> Sub Msg
subscriptions _ =
    Sub.batch
        [ jobEvent (readEvent >> JobEventReceived)
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
      , defaults = DefaultsLoading
      , presets = []
      , presetProblem = Nothing
      , mixer = Nothing
      , renders = Nothing
      , renderJobs = []
      , watchedRender = Nothing
      , rendersProblem = Nothing
      , queue = Nothing
      , queueTick = 0
      , queueProblem = Nothing
      , preview = Preview.Cold
      , previewError = Nothing
      , loopSeconds = Nothing
      , startingRender = Nothing
      , renderError = Nothing
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

        -- Beside the schema rather than on entering the mixer: both describe
        -- the same config and neither changes for the life of the process, so
        -- asking for either later would put a round trip between pressing
        -- "Open the mixer" and seeing one.
        , Request.defaultConfig GotDefaultConfig
        , Request.presets GotPresets
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
                    -- Not the separation's. `jobEvent` is one channel carrying
                    -- every stream this application opens, and the renders
                    -- screen opens one too — so an event nothing here is
                    -- watching falls through to the only other watcher there
                    -- is, which ignores it in turn unless it is theirs.
                    renderJobEvent incoming model

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

        JobEventReceived (Err bad) ->
            unreadableEvent bad model

        JobStreamFailed jobId ->
            case streamFailureFor jobId model.separation of
                StreamIrrelevant ->
                    if model.watchedRender == Just jobId then
                        -- `events.js` has already closed and forgotten it, so
                        -- there is nothing to stop watching. The render is
                        -- still on the worker; the row keeps its status and
                        -- loses only its bar.
                        ( { model
                            | watchedRender = Nothing
                            , rendersProblem =
                                Just
                                    ("Lost the progress stream for a render — it stopped reporting before it finished."
                                        ++ stillRunningNote
                                    )
                          }
                        , Cmd.none
                        )

                    else
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
                            -- Over the server's own defaults when they have
                            -- arrived, and the schema's alone when they have
                            -- not — which the screen then says, because the
                            -- two differ on every stem.
                            state =
                                Mixer.init song.id
                                    schema
                                    song.stems
                                    (publishedDefaults model.defaults)

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

                            -- Belt and braces beside `renderAnswered`'s guard,
                            -- which is what actually stops a failure being
                            -- written where nobody can read it. This is the
                            -- cheap half: a screen opening fresh should not
                            -- inherit a sentence from a previous one whatever
                            -- put it there.
                            , renderError = Nothing

                            -- Same argument, one row up: the bar is the only
                            -- thing that renders this, so a message from the
                            -- last time it was open is a message about a
                            -- screen that has been closed since.
                            , presetProblem = Nothing
                          }
                        , Cmd.batch
                            [ sendPreview toSend

                            -- Re-asked here as well as at startup. The bar is
                            -- the only place presets are visible, so entering
                            -- it is the natural moment to be sure the list is
                            -- current — and the only retry there is for a
                            -- startup fetch that failed.
                            , Request.presets GotPresets

                            -- And the defaults, for the second half of that
                            -- reason alone. They do not change for the life of
                            -- the process, so this is not a refresh — it is the
                            -- retry, and without it a blip during page load
                            -- left every mixer for the rest of the session
                            -- starting every stem eroding identically, under a
                            -- note telling the operator to leave and come back.
                            -- That instruction is only true because of this
                            -- line. The answer lands after this mixer has
                            -- opened, so it is the *next* one that benefits,
                            -- which is exactly what the note promises.
                            , Request.defaultConfig GotDefaultConfig
                            ]
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

        RenderClicked ->
            case model.mixer of
                Nothing ->
                    ( model, Cmd.none )

                Just state ->
                    if renderStartingFor state.songId model || Mixer.everyStemDisabled state then
                        -- Both halves of `Mixer.renderBlock`, because the model
                        -- does not rely on a button being disabled. The first
                        -- is the one that costs something: `POST /api/renders`
                        -- submits unconditionally — unlike `separate_song`,
                        -- which returns the job already in flight — so a second
                        -- click inside one round trip is a second half-hour
                        -- render queued behind the first on the one worker.
                        --
                        -- Asked of *this* song: a render in flight for another
                        -- one is not a reason to refuse this one, and refusing
                        -- it was how a POST on song A silently disabled song
                        -- B's button.
                        ( model, Cmd.none )

                    else
                        let
                            ( request, issued ) =
                                issue model
                        in
                        ( { issued
                            | startingRender =
                                Just { request = request, songId = state.songId }
                            , renderError = Nothing
                          }
                          -- `Mixer.renderConfig`, which is `Config.encode` and
                          -- nothing else — the same encoder every preview
                          -- carries, so the mix that comes out is the one you
                          -- have been listening to. Not `Mixer.params`, whose
                          -- `stems` field holds the soloed stem: a solo is an
                          -- audition, not a decision about the mix.
                        , Request.startRender state.songId
                            (Mixer.renderConfig state)
                            (RenderStarted request)
                        )

        RenderStarted request result ->
            case model.startingRender of
                Nothing ->
                    ( model, Cmd.none )

                Just pending ->
                    if pending.request /= request then
                        -- A POST superseded by a later one, or already
                        -- answered. Adopting it would move a screen on behalf
                        -- of a press this model no longer remembers.
                        ( model, Cmd.none )

                    else
                        renderAnswered pending result { model | startingRender = Nothing }

        OpenRenders ->
            openRenders model

        CloseRenders ->
            -- The list goes; the watch stays. The render is on the server's
            -- worker and keeps going, and its stream is still ours.
            ( { model | renders = Nothing, rendersProblem = Nothing }, Cmd.none )

        GotRenders (Ok renders) ->
            -- The jobs are asked for here rather than beside this request, so
            -- that no row can be paired against a snapshot taken before it
            -- existed. See `refreshRenders`.
            ( { model | renders = Just (Renders.Loaded renders) }
            , Request.jobs GotRenderJobs
            )

        GotRenders (Err err) ->
            -- No rows to pair, so no reason to ask what is behind them.
            ( { model | renders = Just (Renders.Failed (httpErrorToString err)) }, Cmd.none )

        GotRenderJobs (Ok jobs) ->
            -- The snapshot the rows are paired against, plus whichever of them
            -- is worth an event stream. A failed job is kept in the list as
            -- well as a live one: its `error` is the only record of why a
            -- render failed, since the render row has no column for one.
            adoptRenderJob (List.filter (\job -> job.kind == "render") jobs) model

        GotRenderJobs (Err err) ->
            -- Said rather than swallowed. The renders arrive on their own
            -- request and carry their own status, so the list is still right —
            -- but every bar and every Cancel button on it is now drawn from a
            -- snapshot of unknown age, and a stale Cancel is a button that
            -- stops something other than what it is next to. The previous
            -- list is kept rather than cleared, because dropping it would
            -- replace those with the "caught by a restart" paragraph, which
            -- would be a second wrong answer rather than an honest silence.
            ( { model
                | rendersProblem =
                    Just
                        ("Could not refresh what is running — "
                            ++ httpErrorToString err
                            ++ ". Progress and Cancel on this screen are from an "
                            ++ "older snapshot until it succeeds; leave and come "
                            ++ "back to try again."
                        )
              }
            , Cmd.none
            )

        DeleteRenderClicked renderId ->
            ( { model | rendersProblem = Nothing }, Request.deleteRender renderId RenderDeleted )

        RenderDeleted (Ok ()) ->
            ( model, refreshRenders )

        RenderDeleted (Err err) ->
            -- Re-fetched as well as reported: the 409 means this row's status
            -- is older than the server's, and the message tells the user to
            -- cancel a render the row may already be showing as finished.
            ( { model
                | rendersProblem = Just (Renders.deleteMessage err (httpErrorToString err))
              }
            , refreshRenders
            )

        CancelRenderClicked jobId ->
            ( { model | rendersProblem = Nothing }, Request.cancelJob jobId RenderCancelSent )

        RenderCancelSent (Ok answer) ->
            -- Cancelling a *running* render is a request, not an outcome: the
            -- worker stops at its next check, and the render row flips to
            -- `cancelled` after that. A render still queued is now ended by the
            -- server on the spot (`JobManager.cancel`), so its job comes back
            -- already terminal. The re-fetch here shows the job's own new
            -- status either way; the row's follows over the event stream.
            --
            -- `answer.cancelled` is not read on this screen: every row here
            -- carries its own render, and the re-fetch re-states that render's
            -- status, which is the thing this screen is about. The queue screen
            -- does read it, because there a refused cancel is otherwise silent.
            ( { model | renderJobs = Renders.replaceJob answer.job model.renderJobs }
            , refreshRenders
            )

        RenderCancelSent (Err err) ->
            ( { model
                | rendersProblem = Just ("Could not cancel that render — " ++ httpErrorToString err)
              }
            , refreshRenders
            )

        OpenQueue ->
            -- Through `leaveMixer` for the reason `OpenRenders` gives: a
            -- preview loops until something stops it, and a mixer left open
            -- under this screen would go on playing with nothing on screen to
            -- stop it.
            let
                ( closed, stopped ) =
                    leaveMixer model

                ( tick, issued ) =
                    issue closed
            in
            ( { issued
                | queue = Just Queue.Loading
                , queueTick = tick
                , queueProblem = Nothing
                , renders = Nothing
                , rendersProblem = Nothing
              }
            , Cmd.batch [ stopped, Request.jobs GotQueueJobs, scheduleQueueTick tick ]
            )

        CloseQueue ->
            -- The list goes and the poll stops with it, because the poll asks
            -- this field. Nothing else needs unwinding: this screen owns no
            -- event stream, which is the whole reason it polls.
            ( { model | queue = Nothing, queueProblem = Nothing }, Cmd.none )

        QueueTick tick ->
            if model.queueTick /= tick then
                -- A chain left over from an earlier visit. Opening the screen
                -- issues a new tick id, so a stale timer that was still in
                -- flight when the screen closed and reopened lands here, finds
                -- it is not the current one, and stops — rather than running
                -- beside the new chain and doubling the request rate for the
                -- rest of the session.
                ( model, Cmd.none )

            else
                case model.queue of
                    Nothing ->
                        -- Closed. The chain ends here rather than being
                        -- cancelled, because there is nothing to cancel: a
                        -- `Process.sleep` that nobody re-arms simply stops.
                        ( model, Cmd.none )

                    Just _ ->
                        ( model
                        , Cmd.batch [ Request.jobs GotQueueJobs, scheduleQueueTick tick ]
                        )

        GotQueueJobs result ->
            case model.queue of
                Nothing ->
                    -- A poll that landed after the screen closed. Writing it
                    -- back would reopen the screen out from under whatever the
                    -- user is now looking at, since `queue` is what `routeFor`
                    -- reads to decide that.
                    ( model, Cmd.none )

                Just state ->
                    case result of
                        Ok jobs ->
                            -- The note about a cancel goes with the rows it was
                            -- about. It is written when a Cancel does something
                            -- other than what the row implied, and these are the
                            -- rows that show what actually happened — so
                            -- leaving it up over them would be exactly the
                            -- lingering warning `Queue.Stale` exists to avoid,
                            -- one field over. Nothing schedules this: the poll
                            -- that corrects the screen is the poll that clears
                            -- the sentence explaining why it needed correcting.
                            ( { model | queue = Just (Queue.Loaded jobs), queueProblem = Nothing }
                            , Cmd.none
                            )

                        Err err ->
                            -- The rows already on screen are kept: this is a
                            -- poll every few seconds, and one dropped request
                            -- must not replace a live queue with an error
                            -- line. `Stale` carries the rows and the reason
                            -- together, so the next poll that succeeds clears
                            -- the warning by replacing the state rather than by
                            -- remembering to blank a field.
                            ( { model | queue = Just (Queue.afterFailedPoll (httpErrorToString err) state) }
                            , Cmd.none
                            )

        CancelJobClicked jobId ->
            ( { model | queueProblem = Nothing }, Request.cancelJob jobId JobCancelSent )

        JobCancelSent (Ok answer) ->
            -- Two outcomes behind one 200, and only `cancelled` tells them
            -- apart. It is False when the job was already terminal at the
            -- moment the server looked — reachable by ordinary use, since the
            -- button is drawn from a poll up to `queueInterval` old — and that
            -- deserves a sentence, or the button did nothing and said nothing
            -- about it.
            --
            -- Deriving this from the returned job's status instead would be
            -- wrong in a real case: the route cancels and then re-reads, so a
            -- running job genuinely cancelled can come back `done` if the
            -- worker finished it in that window, and the screen would report
            -- "nothing was stopped" about a cancel that worked.
            --
            -- No re-fetch on the refused branch, deliberately: the note lives
            -- exactly until the next poll, which is the same poll that brings
            -- the corrected row. Fetching here would clear it in the same
            -- breath as writing it. The successful branch does re-fetch, so a
            -- queued job — which the server now ends on the spot — shows as
            -- cancelled immediately rather than four seconds later.
            if answer.cancelled then
                ( { model | queueProblem = Nothing }, Request.jobs GotQueueJobs )

            else
                ( { model
                    | queueProblem =
                        Just
                            ("That job had already finished, so nothing was "
                                ++ "stopped — the row was from the last poll."
                            )
                  }
                , Cmd.none
                )

        JobCancelSent (Err err) ->
            ( { model
                | queueProblem = Just ("Could not cancel that job — " ++ httpErrorToString err)
              }
            , Request.jobs GotQueueJobs
            )

        GotPresets (Ok presets) ->
            -- The list, and deliberately *not* a clear of `presetProblem`. A
            -- refused delete both writes its reason and re-fetches — the row
            -- may have changed under it — so clearing here would wipe the
            -- sentence in the same breath as writing it, exactly the mistake
            -- `JobCancelSent`'s refused branch avoids one screen along. The
            -- message is cleared where it was raised from: entering the mixer,
            -- leaving it, and every button that starts a new attempt.
            ( { model | presets = presets }, Cmd.none )

        GotPresets (Err err) ->
            -- Said rather than swallowed, and said in the bar, which is the
            -- only place presets appear at all. An empty select with no
            -- explanation reads as "you have never saved one", which is a
            -- different and much worse sentence than the true one.
            ( { model
                | presetProblem =
                    Just
                        ("Could not load your presets — "
                            ++ httpErrorToString err
                            ++ ". Leave the mixer and open it again to try that fetch once more."
                        )
              }
            , Cmd.none
            )

        GotDefaultConfig (Ok published) ->
            ( { model | defaults = DefaultsReady published }, Cmd.none )

        GotDefaultConfig (Err err) ->
            ( { model | defaults = DefaultsUnavailable (httpErrorToString err) }, Cmd.none )

        PresetSelected raw ->
            -- Choosing is not applying, so nothing is sent: `withMixer` would
            -- fire a preview of a config that has not changed.
            ( mapMixer (Mixer.selectPreset raw) model, Cmd.none )

        PresetNameChanged raw ->
            ( mapMixer (Mixer.setPresetName raw) model, Cmd.none )

        PresetPending pending ->
            ( mapMixer (Mixer.armConfirm pending) model, Cmd.none )

        PresetApplied presetId ->
            case ( model.mixer, model.settings ) of
                ( Just state, SettingsReady schema ) ->
                    case Mixer.presetById model.presets (Just presetId) of
                        Just preset ->
                            -- Through `withMixer`, which is the same door
                            -- every slider and checkbox goes through: it hands
                            -- the new config to `Preview.request` and sends
                            -- whatever that decides to send. Nothing here
                            -- touches the audio port, and an apply is exactly
                            -- one control change — a large one.
                            withMixer (Mixer.applyPreset schema (publishedDefaults model.defaults) preset)
                                { model | presetProblem = Nothing }
                                |> andThen (rememberPreset state.songId preset.id)

                        Nothing ->
                            -- Unreachable from the bar: the select is built
                            -- from the same list this resolves against, so an
                            -- id that does not resolve is not on screen to be
                            -- pressed. Doing nothing beats inventing a message
                            -- about a preset nobody can see.
                            ( model, Cmd.none )

                _ ->
                    ( model, Cmd.none )

        SavePresetAs ->
            case model.mixer of
                Nothing ->
                    ( model, Cmd.none )

                Just state ->
                    case Mixer.newPresetName state of
                        Nothing ->
                            -- The button is disabled without a name; the model
                            -- does not rely on that being true.
                            ( model, Cmd.none )

                        Just name ->
                            ( { model | presetProblem = Nothing }
                              -- `Config.forPreset`, never `Config.encode`: a
                              -- preset must not carry this song's loop region
                              -- or a separation model, and both are silent
                              -- when they are wrong.
                            , Request.createPreset name
                                (Config.forPreset state.config)
                                -- Tagged with the song whose mixer is saving,
                                -- because the answer lands at a model that may
                                -- have moved on. See `PresetSaved`.
                                (PresetSaved state.songId)
                            )

        PresetSaved songId (Ok preset) ->
            -- The preset exists whatever screen is now open, so the *song* half
            -- of this is unconditional: the save came from that song's mixer,
            -- and that is the song which last used it. The *screen* half is
            -- not. A save issued on song A that answers after song B's mixer
            -- has opened must not move B's select to a preset nobody applied
            -- there — the same call `renderAnswered` makes one panel along, and
            -- the same window: a POST outlives the screen that sent it.
            ( if mixerOpenFor songId model then
                mapMixer (Mixer.presetSaved preset) { model | presetProblem = Nothing }

              else
                model
            , Cmd.batch
                [ Request.presets GotPresets
                , Request.setLastPreset songId (Just preset.id) (LastPresetSet songId)
                ]
            )

        PresetSaved songId (Err err) ->
            -- Written only where it can be read, exactly as `renderError` is: a
            -- failure reported on a different song's mixer is not a lost
            -- message but a planted one.
            if mixerOpenFor songId model then
                ( { model | presetProblem = Just (Mixer.saveMessage err (httpErrorToString err)) }
                , Cmd.none
                )

            else
                ( model, Cmd.none )

        SaveOverConfirmed ->
            case model.mixer of
                Nothing ->
                    ( model, Cmd.none )

                Just state ->
                    case Mixer.selection model.presets state of
                        Nothing ->
                            ( model, Cmd.none )

                        Just preset ->
                            -- The preset's own name goes back unchanged: this
                            -- button replaces what a preset holds, and the one
                            -- route covers renaming too only because the
                            -- server needed both in one call.
                            ( mapMixer (Mixer.armConfirm Nothing)
                                { model | presetProblem = Nothing }
                            , Request.updatePreset preset.id
                                preset.name
                                (Config.forPreset state.config)
                                (PresetUpdated state.songId)
                            )

        PresetUpdated songId (Ok preset) ->
            ( model
            , Cmd.batch
                [ Request.presets GotPresets
                , Request.setLastPreset songId (Just preset.id) (LastPresetSet songId)
                ]
            )

        PresetUpdated songId (Err err) ->
            if mixerOpenFor songId model then
                ( { model | presetProblem = Just (Mixer.saveMessage err (httpErrorToString err)) }
                , Cmd.none
                )

            else
                ( model, Cmd.none )

        DeletePresetConfirmed ->
            case model.mixer of
                Nothing ->
                    ( model, Cmd.none )

                Just state ->
                    case Mixer.selection model.presets state of
                        Nothing ->
                            ( model, Cmd.none )

                        Just preset ->
                            ( mapMixer (Mixer.armConfirm Nothing)
                                { model | presetProblem = Nothing }
                            , Request.deletePreset preset.id (PresetDeleted state.songId)
                            )

        PresetDeleted songId (Ok ()) ->
            -- The selection is dropped by the re-fetch rather than here: it is
            -- an id resolved against the list every time it is read, so a list
            -- without that preset in it is already a bar with nothing
            -- selected. Clearing it explicitly as well, because a select whose
            -- value names a row that no longer exists is a browser deciding
            -- for itself which option to show.
            ( if mixerOpenFor songId model then
                mapMixer (Mixer.selectPreset "") model

              else
                model
            , Request.presets GotPresets
            )

        PresetDeleted songId (Err err) ->
            if mixerOpenFor songId model then
                ( { model
                    | presetProblem =
                        Just ("Could not delete that preset — " ++ httpErrorToString err)
                  }
                , Request.presets GotPresets
                )

            else
                ( model, Request.presets GotPresets )

        LastPresetSet _ (Ok updated) ->
            -- The song row comes back with its new `last_preset_id`, which is
            -- what the "Last used here" line reads. Adopted only while that
            -- song is still the one on screen: this answers after a round trip
            -- and the operator may have moved on, and writing it then would
            -- put another song's row under an open mixer. Asked of the returned
            -- row's own id, which is the song this was issued for.
            if model.selectedSongId == Just updated.id then
                ( { model | currentSong = Just updated }, Cmd.none )

            else
                ( model, Cmd.none )

        LastPresetSet songId (Err err) ->
            -- The preset *was* applied — this is only the note of which one,
            -- and the note failing is not the apply failing. Said anyway,
            -- because the "Last used here" line silently not appearing next
            -- time is the kind of small unexplained absence this interface
            -- keeps deciding against.
            --
            -- And said only to the screen it happened on, which its `Ok`
            -- sibling has always been careful about and this was not: the write
            -- can land after a close and a reopen, and would then greet the
            -- next session with a complaint about the previous one.
            if mixerOpenFor songId model then
                ( { model
                    | presetProblem =
                        Just
                            ("That preset is applied, but this song could not be made to "
                                ++ "remember it — "
                                ++ httpErrorToString err
                                ++ ". The mix on screen is unaffected."
                            )
                  }
                , Cmd.none
                )

            else
                ( model, Cmd.none )


{-| An unreadable frame, charged to whichever stream sent it and to no other.

The work started fine; the *event* was unreadable. Whichever watch it belongs
to ends cleanly and says so where that watch is visible — `eventError` is
rendered by the song screen and `rendersProblem` by the renders screen, so
writing to the wrong one is the same as saying nothing.

The stream is closed explicitly, unlike the `JobStreamFailed` path: this is a
frame `events.js` delivered happily and Elm could not read, so the connection is
still open and still ours, and nothing further can be trusted from it.

When the id itself cannot be read, *both* watches end. A frame with no id is
not a job event at all, both streams are the same shape from the same server,
and there is no evidence pointing at either — so the choice is between ending
both and guessing. Guessing is what the previous version did, always in favour
of the separation, and it closed healthy ones while Demucs kept running.
-}
unreadableEvent : BadEvent -> Model -> ( Model, Cmd Msg )
unreadableEvent bad model =
    let
        lost subject =
            "Lost track of "
                ++ subject
                ++ " — a progress event could not be read: "
                ++ bad.detail
                ++ "."
                ++ stillRunningNote

        endSeparation =
            ( { model | separation = Idle, eventError = Just (lost "the separation") }
            , stopWatching (watchedJobId model.separation)
            )

        endRenderWatch =
            ( { model | watchedRender = Nothing, rendersProblem = Just (lost "a render") }
            , stopWatching model.watchedRender
            )
    in
    case bad.jobId of
        Just jobId ->
            if watchedJobId model.separation == Just jobId then
                endSeparation

            else if model.watchedRender == Just jobId then
                endRenderWatch

            else
                -- Neither of ours. Nothing to end and nothing to say.
                ( model, Cmd.none )

        Nothing ->
            let
                watchingSeparation =
                    watchedJobId model.separation /= Nothing

                watchingRender =
                    model.watchedRender /= Nothing
            in
            if not watchingSeparation && not watchingRender then
                -- Nothing open for it to have come from. Ending watches that
                -- do not exist and apologising for them would be noise.
                ( model, Cmd.none )

            else
                ( { model
                    | separation =
                        if watchingSeparation then
                            Idle

                        else
                            model.separation
                    , watchedRender = Nothing
                    , eventError =
                        if watchingSeparation then
                            Just (lost "the separation")

                        else
                            model.eventError
                    , rendersProblem =
                        if watchingRender then
                            Just (lost "a render")

                        else
                            model.rendersProblem
                  }
                , Cmd.batch
                    [ stopWatching (watchedJobId model.separation)
                    , stopWatching model.watchedRender
                    ]
                )


{-| What `POST /api/renders` coming back means, for the song that asked.

Both branches are conditional on that song still being the one on screen, and
both conditions exist because the answer arrives at a model that has moved on
from the one that sent it.

**Success moves to the renders screen, but only if the render's own song is
still open.** Leaving the mixer while a POST is in flight is not a reason to
drop the navigation — the click asked for it, and closing the mixer is not
closing the song — so this reads `selectedSongId` rather than the mixer. But
opening a *different* song is: `openRenders` goes through `leaveMixer`, so a
render started on song A would otherwise close song B's mixer and stop its
preview, which is one song's action reaching into another's screen. Going back
to the library counts as leaving too, and the render is on the renders screen
whenever the user chooses to look.

**A failure is written only where it can be read.** `renderError` is rendered by
the mixer and by nothing else, so a write with no mixer open — or with a
different song's mixer open — does not lose a message, it plants one: it sits in
the model until the next mixer opens and then reports a failure about a song
that is no longer on screen. `leaveMixer` clearing the field cannot prevent that
on its own, because the write can land after the leave.

The job in a successful response is deliberately not written into `renderJobs`
here. `openRenders` re-fetches the renders and then the jobs, in that order and
for that reason; a job inserted beside it would be a second source for the same
row.
-}
renderAnswered : PendingRender -> Result Http.Error Api.Job -> Model -> ( Model, Cmd Msg )
renderAnswered pending result model =
    case result of
        Ok _ ->
            if model.selectedSongId == Just pending.songId then
                openRenders model

            else
                ( model, Cmd.none )

        Err err ->
            if mixerOpenFor pending.songId model then
                ( { model | renderError = Just (httpErrorToString err) }, Cmd.none )

            else
                ( model, Cmd.none )


{-| Open the renders screen, from the nav strip or from a render just started.

One function rather than the same six fields written twice, because the two
callers must not drift: a render started from the mixer that opened the screen
without closing the queue would leave `routeFor`'s order between them
load-bearing, which the docstring there says it is not.

Through `leaveMixer` rather than beside it: a preview loops until something
stops it, and a mixer left open under this screen would go on playing with
nothing on screen to stop it. That applies to the render path too — starting a
render does not stop the audio, but arriving at this screen does, exactly as
arriving from the nav strip always has.
-}
openRenders : Model -> ( Model, Cmd Msg )
openRenders model =
    let
        ( closed, stopped ) =
            leaveMixer model
    in
    ( { closed
        | renders = Just Renders.Loading
        , rendersProblem = Nothing

        -- The two nav screens are alternatives, not layers. Closing the queue
        -- here is what makes `routeFor`'s order between them not matter, and it
        -- is also what ends the queue's poll: the next tick reads `Nothing` and
        -- stops.
        , queue = Nothing
        , queueProblem = Nothing
      }
    , Cmd.batch [ stopped, refreshRenders ]
    )


{-| The renders, and then the jobs behind them.

Two requests, deliberately sequenced rather than batched. Concurrently, the
jobs response could be served *before* a `POST /api/renders` lands and the
renders response *after* it, leaving a brand-new row paired against a job
snapshot that predates it — a queued, perfectly cancellable render wearing the
"caught by a restart, nothing to cancel" paragraph, and wearing it until the
user leaves the screen and comes back. Fetching the jobs from `GotRenders`
means the jobs snapshot is never older than the renders it is paired against.

Fired on entering the screen and after anything that could have changed either
— which is every delete and every cancel, since a delete refused with a 409
means the row was staler than the server.
-}
refreshRenders : Cmd Msg
refreshRenders =
    Request.renders GotRenders


{-| How often the queue screen re-asks what the worker is doing.

Four seconds: long enough that a screen left open costs almost nothing, short
enough that a job finishing and the next one starting shows up while you are
still looking at it. `GET /api/jobs` reads a dictionary under a lock and
serialises it; there is no query behind it.
-}
queueInterval : Float
queueInterval =
    4000


{-| The next poll, as a command rather than a subscription.

This is `Time.every` written by hand, and it is written by hand for one reason:
`elm/time` is an *indirect* dependency of this application, so `Time` cannot be
imported without promoting it in `elm.json` — which is a change to the declared
dependency set, and this branch is not making one. `Process.sleep` and
`Task.perform` are both `elm/core`, which is already direct.

What that costs is the thing a subscription gives for free: a subscription
derived from the model stops existing the moment the model says the screen is
closed, whereas a sleep already in flight will still land. So the tick carries
the id of the chain that scheduled it and `QueueTick` checks two things before
re-arming — that the id is still current, and that the screen is still open.
A stale tick does nothing at all; it does not poll and it does not reschedule.
-}
scheduleQueueTick : Int -> Cmd Msg
scheduleQueueTick tick =
    Process.sleep queueInterval |> Task.perform (\_ -> QueueTick tick)


refreshRendersIfOpen : Model -> Cmd Msg
refreshRendersIfOpen model =
    case model.renders of
        Just _ ->
            refreshRenders

        Nothing ->
            Cmd.none


{-| Take the polled job list, and hold one stream open over the job that is
actually moving.

Only one, and only ever one: `events.js` opens a connection per job and the
manager fans out per subscriber, so a screen with ten rows watching ten streams
would be ten connections to report one worker's progress. Re-adopting the job
already being watched is a no-op rather than a reconnect — `watchJob` is
idempotent on the JavaScript side, but saying so here keeps the model's
`watchedRender` meaning exactly "the stream we own".
-}
adoptRenderJob : List Api.Job -> Model -> ( Model, Cmd Msg )
adoptRenderJob jobs model =
    let
        updated =
            { model
                | renderJobs =
                    Renders.keepStreamed model.watchedRender model.renderJobs jobs
            }
    in
    case Renders.liveRenderJob jobs of
        Nothing ->
            ( updated, Cmd.none )

        Just live ->
            if model.watchedRender == Just live.id then
                ( updated, Cmd.none )

            else
                ( { updated | watchedRender = Just live.id }
                , Cmd.batch [ stopWatching model.watchedRender, watchJob live.id ]
                )


{-| An event for the render we are streaming.

The finished job is kept rather than dropped: a `Failed` job carries the only
description of what went wrong that exists anywhere, and the row it belongs to
is about to be re-fetched as `failed` with nothing of its own to say. The
re-fetch also re-polls the job list, which is what picks up the next queued
render and starts watching that instead.
-}
renderJobEvent : Api.Job -> Model -> ( Model, Cmd Msg )
renderJobEvent incoming model =
    if model.watchedRender /= Just incoming.id then
        ( model, Cmd.none )

    else
        let
            updated =
                { model | renderJobs = Renders.replaceJob incoming model.renderJobs }
        in
        if Api.isFinished incoming.status then
            ( { updated | watchedRender = Nothing }
            , Cmd.batch [ stopWatchingJob incoming.id, refreshRendersIfOpen model ]
            )

        else
            ( updated, Cmd.none )


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

Note what is *not* here: any test of whether a request should go out *yet*. The
scrubber emits a message per pixel of drag and each one arrives here; which of
them reaches the server is `Preview.request`'s decision alone, and this passes
on whatever it hands back. A condition of the form "only if nothing is in
flight" written here would be the same logic in a place `elm-test` cannot
reach, which is the whole argument for `Preview.elm` existing.

`everyStemDisabled` is a different question and not an exception to that one.
It is not about timing or coalescing — it is that the config now describes a
mix of nothing, which the server refuses with a 400 (`preview.render_window`).
Sending it anyway would turn an unticked checkbox into a preview that appears
to break. The predicate lives in `Page.Mixer` beside the config it reads, so it
is as testable as anything in `Preview`; only the choice to consult it is here.
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
            in
            if Mixer.everyStemDisabled updated then
                -- The mixer says so on screen, and the last preview keeps
                -- looping — the alternative is a request we know comes back
                -- 400, and an error line blaming the server for a choice the
                -- user just made.
                ( { model | mixer = Just updated }, Cmd.none )

            else
                let
                    ( preview, toSend ) =
                        Preview.request (Mixer.params updated) model.preview
                in
                ( { model | mixer = Just updated, preview = preview }, sendPreview toSend )


{-| A change to the mixer that is not a change to the mix.

`withMixer`'s sibling, and the difference between them is the whole of it:
that one hands the new config to `Preview.request`, this one does not. Choosing
a preset in the select, typing a name, and arming a confirm all change what the
screen shows and nothing about what is playing — passing them through
`withMixer` would fire a preview of a config that has not moved, and a scrubber
drag would then be competing with keystrokes in a name box for the one request
slot.
-}
mapMixer : (Mixer.State -> Mixer.State) -> Model -> Model
mapMixer change model =
    { model | mixer = Maybe.map change model.mixer }


{-| Remember this preset as the one this song last had.

`songs.last_preset_id` exists for exactly one line on one screen — "Last used
here" — and is never applied on its own. Written when a preset is applied and
when one is saved from this song's mixer, which are the two moments the song
and the preset were last the same thing.

Takes the song rather than reading it off whatever mixer is open. An apply is
synchronous and could have read it, but a save answers after a round trip, and
this used to be the same function for both: the song was read at *answer* time,
so a "Save as…" in song A's mixer that came back after song B's had opened
wrote A's preset onto B's row, and B then offered to re-apply a preset never
used on it. Naming the song at the moment the request is issued is what
`Separation.Starting` and `PendingRender` both do, for this exact window.
-}
rememberPreset : String -> String -> Model -> ( Model, Cmd Msg )
rememberPreset songId presetId model =
    ( model, Request.setLastPreset songId (Just presetId) (LastPresetSet songId) )


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

`renderError` goes with the screen that shows it. `startingRender` deliberately
does not: the render is on the server whether or not anyone is still looking at
the mixer, and clearing the id would make an arriving success land nowhere
rather than at the renders screen the click asked for. It is the same call
`CloseRenders` makes about `watchedRender` one screen along.
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
                , renderError = Nothing

                -- The preset bar is the only thing that renders this, so a
                -- message left behind here would reappear over the next
                -- mixer — about a save that happened on a different song.
                , presetProblem = Nothing
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

            QueueView state ->
                queueView model state

            RendersView state ->
                rendersView model state

            SongView songId ->
                songView model songId

            MixerView state ->
                mixerView model state
        ]


{-| The renders screen, and the song list's way into it.

The songs come from the library fetch that has already happened rather than
from one of this screen's own: a render carries a `song_id` and nothing else
about the song it came from, and `Page.Renders.titleFor` is what turns that
back into a title — or leaves it as the id, for a song that has since been
removed out from under a render that outlived it.
-}
rendersView : Model -> Renders.State -> Html Msg
rendersView model state =
    Renders.view
        { state = state
        , songs =
            case model.library of
                Library.Loaded songs ->
                    songs

                _ ->
                    []
        , jobs = model.renderJobs
        , problem = model.rendersProblem
        , onDelete = DeleteRenderClicked
        , onCancel = CancelRenderClicked
        , onBack = CloseRenders
        }


{-| The queue screen.

Takes the library's songs for the same reason the renders screen does: a job
carries a `song_id` and nothing else about the song, and this is the only place
that id can be turned back into a title. A song removed out from under a job
that outlived it falls back to the id rather than to a blank cell.

`songs` is `[]` while the library fetch is still in flight, which reads as every
row showing an id for a second. That beats withholding the screen: someone
opening the queue is usually trying to stop something.
-}
queueView : Model -> Queue.State -> Html Msg
queueView model state =
    Queue.view
        { state = state
        , songs =
            case model.library of
                Library.Loaded songs ->
                    songs

                _ ->
                    []
        , problem = model.queueProblem
        , onCancel = CancelJobClicked
        , onBack = CloseQueue
        }


libraryView : Model -> Html Msg
libraryView model =
    div []
        [ div [ class "nav" ]
            [ button [ onClick OpenQueue ] [ text "Queue" ]
            , button [ onClick OpenRenders ] [ text "Renders" ]
            ]
        , Library.view
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

        -- Directly under the separation panel, which is the last thing
        -- `Page.Song.view` draws and the thing this is for. Nothing on this
        -- screen can stop a separation — `Page.Song` has no cancel path at all
        -- — so the queue is the only way to, and it was reachable only from the
        -- library: back out of the song you are watching, then across. This is
        -- the screen where you sit watching a bar crawl and decide you picked
        -- the wrong file, so it is the screen the way out belongs on.
        , div [ class "nav" ]
            [ button [ onClick OpenQueue ] [ text "Queue" ] ]
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
                    , startingRender = renderStartingFor song.id model
                    , renderError = model.renderError
                    , presets = model.presets
                    , presetProblem = model.presetProblem
                    , onBack = CloseMixer
                    , onProgress = ProgressChanged
                    , onSolo = SoloToggled
                    , onField = FieldChanged
                    , onToggle = FieldToggled
                    , onRetry = RetryPreview
                    , onRender = RenderClicked
                    , onPresetSelected = PresetSelected
                    , onPresetApplied = PresetApplied
                    , onPresetName = PresetNameChanged
                    , onPresetSaveAs = SavePresetAs
                    , onPresetPending = PresetPending
                    , onPresetSaveOver = SaveOverConfirmed
                    , onPresetDelete = DeletePresetConfirmed
                    }
                , errorLine (\reason -> "Could not find the loop — " ++ reason) model.loopError

                -- Why the mixer had to fall back to the schema's defaults, as
                -- opposed to *that* it did, which the bar itself states. The
                -- reason lives here because this is where every other
                -- `Http.Error` on this screen is turned into a sentence.
                , defaultsProblem model.defaults
                ]

        _ ->
            p [ class "dim" ] [ text "Loading the mixer…" ]


{-| Why the server's own defaults are not here.

Unlike the schema, this does not stop the mixer opening — it opens at the
schema's defaults and says so — so this is the reason rather than the fact, and
it is not an error line in red for the same reason: nothing is broken, the
starting point is merely a different one from the tool's own.
-}
defaultsProblem : Defaults -> Html msg
defaultsProblem defaults =
    case defaults of
        DefaultsUnavailable reason ->
            p [ class "dim" ]
                [ text
                    ("The server's default config could not be fetched — "
                        ++ reason
                        ++ "."
                    )
                ]

        _ ->
            text ""


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
