module MixerTest exposing (suite)

{-| The mixer's own decisions, and the ones `Main` makes on its behalf.

Two things are being defended here. The first is solo: it decides what
`stems` a preview carries, and the difference between "none" and "all" is one
empty list — sent literally, the server previews silence. The second is that
nothing reaches the port before the session is warm, and that everything which
leaves the mixer stops the audio: a preview loops until told otherwise, so the
failure mode is music playing under a screen with no way to stop it.

`Cmd` has no equality in Elm, so what these assert is the model half — which
for the preview path is the whole decision, because the command is derived
from the state `Preview` hands back and nothing else.

-}

import Api
import Config
import Expect
import Fixtures
import Http
import Json.Decode as Decode
import Main
import Page.Mixer as Mixer
import Page.Renders as Renders
import Preview
import Test exposing (Test, describe, test)
import Test.Html.Event as Event
import Test.Html.Query as Query
import Test.Html.Selector as Selector


song : Api.Song
song =
    { id = "song-1"
    , path = "/tmp/a.wav"
    , title = "A"
    , durationS = 210.0
    , sampleRate = 44100
    , separationStatus = Api.Separated
    , stems = [ "vocals", "drums", "bass" ]
    , lastPresetId = Nothing
    , addedAt = "2026-08-04"
    }


mixer : Mixer.State
mixer =
    Mixer.init "song-1" Fixtures.schema song.stems


step : Main.Msg -> Main.Model -> Main.Model
step msg model =
    Tuple.first (Main.update msg model)


{-| A song open, its detail loaded, and the schema in hand — everything
`OpenMixer` needs.
-}
onSong : Api.Song -> Main.Model
onSong s =
    { fresh
        | selectedSongId = Just s.id
        , currentSong = Just s
        , settings = Main.SettingsReady Fixtures.schema
    }


opened : Main.Model
opened =
    step Main.OpenMixer (onSong song)


{-| Playing, as it is once the opening preview has come back.
-}
warm : Main.Model
warm =
    step (Main.PreviewPlaying (Just 12.5)) opened


{-| `Preview.State` has no `toString`, and comparing whole states means
building the `Params` inside them — including an encoded config — to assert
something these tests do not care about.
-}
phase : Preview.State -> String
phase state =
    case state of
        Preview.Cold ->
            "Cold"

        Preview.Warming ->
            "Warming"

        Preview.Idle ->
            "Idle"

        Preview.InFlight _ ->
            "InFlight"

        Preview.Queued _ ->
            "Queued"


{-| What a preview built from this model would actually carry, decoded out of
the encoded config along the paths `MixConfig.from_dict` walks.

`Mixer.params` is where a control change stops being a model update and starts
being a request, so asserting here rather than on `state.config` is what makes
these tests about the button rather than about the setter behind it.
-}
carried : Decode.Decoder a -> Main.Model -> Maybe (Result Decode.Error a)
carried decoder model =
    model.mixer
        |> Maybe.map (Mixer.params >> .config >> Decode.decodeValue decoder)


stemField : Int -> String -> Decode.Decoder a -> Decode.Decoder a
stemField index key decoder =
    Decode.field "stems" (Decode.index index (Decode.field key decoder))


{-| Untick (or retick) the Enabled box on the stem in row `index`, as the
generated checkbox does.
-}
enabling : Int -> Bool -> Main.Msg
enabling index on =
    Main.FieldToggled (Config.InStem index "enabled") on


{-| Back to a state where a change would be sent, so that "nothing was sent"
is observable rather than hidden behind a request that was already queued.
-}
idle : Main.Model -> Main.Model
idle model =
    { model | preview = Preview.Idle }


{-| Two of `warm`'s three stems switched off. -}
oneStemLeft : Main.Model
oneStemLeft =
    idle (warm |> step (enabling 0 False) |> step (enabling 1 False))


{-| And the third. -}
everyStemOff : Main.Model
everyStemOff =
    idle (oneStemLeft |> step (enabling 2 False))


{-| What `POST /api/renders` answers with: the job, out of the envelope
`Request.startRender` decodes.
-}
startedJob : Api.Job
startedJob =
    { id = "job-1"
    , kind = "render"
    , status = Api.Queued
    , fraction = 0
    , message = ""
    , songId = Just "song-1"
    , renderId = Just "render-1"
    , createdAt = "2026-08-05T22:10:00.123456+00:00"
    }


{-| Answer whichever render POST this model has in flight.

Reads the request id off the model rather than assuming one, because it is
issued by the same counter every other request uses and hard-coding a number
would make these tests depend on how many requests happened to precede them.
-}
answered : Result Http.Error Api.Job -> Main.Model -> Main.Model
answered result model =
    case model.startingRender of
        Just pending ->
            step (Main.RenderStarted pending.request result) model

        Nothing ->
            model


{-| A second song, to open in front of the first one's render.
-}
songB : Api.Song
songB =
    { song | id = "song-2", title = "B" }


{-| A song, opened the way opening a song actually happens: select it, let its
detail land, open the mixer on it.

Driven through `update` rather than assembled by hand, because the bug these
exist for is about state one screen leaves behind for the next and a
hand-built model is exactly where that would be papered over.
-}
openSong : Api.Song -> Main.Model -> Main.Model
openSong s model =
    let
        selected =
            step (Main.SelectedSong s.id) model
    in
    selected
        |> step (Main.GotSongDetail selected.songRequest (Ok s))
        |> step Main.OpenMixer


{-| The seventy-minute file, which is the one the warning exists for.
-}
longSong : Api.Song
longSong =
    { song | durationS = 4188 }


longWarm : Main.Model
longWarm =
    onSong longSong
        |> step Main.OpenMixer
        |> step (Main.PreviewPlaying (Just 12.5))


{-| The whole application as it would render, not a hand-built view config.

Through `Main.view` deliberately. A `Page.Mixer.view` called directly with a
record written here would prove the panel's markup and nothing about whether
`Main` wires `onRender` to `RenderClicked` — and any other `Msg` compiles
there.
-}
screen : Main.Model -> Query.Single Main.Msg
screen model =
    Query.fromHtml (Main.view model)


suite : Test
suite =
    describe "the mixer"
        [ describe "the controls, driven through `update`"
            -- These exist because replacing `SoloToggled`, `FieldChanged` and
            -- `FieldToggled` with `( model, Cmd.none )` — every solo button and
            -- every generated control inert — used to leave the whole suite
            -- green. `Mixer.toggleSolo` and `Mixer.params` were called
            -- directly and the button path was never touched.
            [ test "a typed or dragged value reaches the config a preview carries" <|
                \_ ->
                    warm
                        |> step (Main.FieldChanged (Config.InStem 1 "gain_db") "-6.5")
                        |> carried (stemField 1 "gain_db" Decode.float)
                        |> Expect.equal (Just (Ok -6.5))
            , test "and that value goes out" <|
                \_ ->
                    warm
                        |> step (Main.FieldChanged (Config.InStem 1 "gain_db") "-6.5")
                        |> .preview
                        |> phase
                        |> Expect.equal "InFlight"
            , test "a checkbox reaches it too" <|
                \_ ->
                    warm
                        |> step (enabling 1 False)
                        |> carried (stemField 1 "enabled" Decode.bool)
                        |> Expect.equal (Just (Ok False))
            , test "and that checkbox goes out" <|
                \_ ->
                    warm
                        |> step (enabling 1 False)
                        |> .preview
                        |> phase
                        |> Expect.equal "InFlight"
            , test "a solo button reaches the stems a preview carries" <|
                \_ ->
                    warm
                        |> step (Main.SoloToggled "drums")
                        |> .mixer
                        |> Maybe.map (Mixer.params >> .stems)
                        |> Expect.equal (Just [ "drums" ])
            , test "and that solo goes out" <|
                \_ ->
                    warm
                        |> step (Main.SoloToggled "drums")
                        |> .preview
                        |> phase
                        |> Expect.equal "InFlight"
            ]
        , describe "switching off the stem that is soloed"
            -- The Solo button is disabled on a switched-off stem, which closes
            -- one order only. Solo first, then untick Enabled, and the request
            -- asks for a mix of exactly one disabled stem — 200 and a 48-byte
            -- WAV before the server started refusing it, and still a request
            -- with no answer worth playing.
            [ test "clears the solo rather than reporting an impossible one" <|
                \_ ->
                    mixer
                        |> Mixer.toggleSolo "drums"
                        |> Mixer.toggleField (Config.InStem 1 "enabled") False
                        |> Mixer.soloedStems
                        |> Expect.equal []
            , test "through the button path as well" <|
                \_ ->
                    warm
                        |> step (Main.SoloToggled "drums")
                        |> step (enabling 1 False)
                        |> .mixer
                        |> Maybe.map (Mixer.params >> .stems)
                        |> Expect.equal (Just [])
            , test "switching off a different stem leaves the solo alone" <|
                \_ ->
                    mixer
                        |> Mixer.toggleSolo "drums"
                        |> Mixer.toggleField (Config.InStem 0 "enabled") False
                        |> Mixer.soloedStems
                        |> Expect.equal [ "drums" ]
            , test "and switching one back on does not invent a solo" <|
                \_ ->
                    mixer
                        |> Mixer.toggleField (Config.InStem 1 "enabled") True
                        |> Mixer.soloedStems
                        |> Expect.equal []
            ]
        , describe "switching off every stem"
            -- The server refuses this with a 400 rather than playing the full
            -- default mix, which is what it used to do. A refusal that arrives
            -- after the request still reads as a preview that broke, so the
            -- request is not sent and the mixer says why.
            [ test "the mixer knows there is nothing left to render" <|
                \_ ->
                    everyStemOff.mixer
                        |> Maybe.map Mixer.everyStemDisabled
                        |> Expect.equal (Just True)
            , test "one still on is not that state" <|
                \_ ->
                    oneStemLeft.mixer
                        |> Maybe.map Mixer.everyStemDisabled
                        |> Expect.equal (Just False)
            , test "a change with one stem left goes out" <|
                \_ ->
                    -- The control for the assertion below: same model, same
                    -- message, one stem's difference.
                    oneStemLeft
                        |> step (Main.ProgressChanged "0.5")
                        |> .preview
                        |> phase
                        |> Expect.equal "InFlight"
            , test "and with none left, nothing is sent" <|
                \_ ->
                    everyStemOff
                        |> step (Main.ProgressChanged "0.5")
                        |> .preview
                        |> phase
                        |> Expect.equal "Idle"
            , test "though the change is still kept, so switching one back on plays it" <|
                \_ ->
                    everyStemOff
                        |> step (Main.ProgressChanged "0.5")
                        |> .mixer
                        |> Maybe.map .progress
                        |> Expect.equal (Just 0.5)
            ]
        , describe "solo"
            [ test "nothing soloed asks for no stems in particular" <|
                \_ ->
                    -- Not "every stem, listed": `Preview.encode` omits an
                    -- empty list and the server reads a missing `stems` as
                    -- all of them. A list built here could disagree with what
                    -- separation actually produced.
                    Mixer.soloedStems mixer |> Expect.equal []
            , test "soloing a stem asks for exactly that one" <|
                \_ ->
                    mixer
                        |> Mixer.toggleSolo "drums"
                        |> Mixer.soloedStems
                        |> Expect.equal [ "drums" ]
            , test "soloing it again restores all of them" <|
                \_ ->
                    mixer
                        |> Mixer.toggleSolo "drums"
                        |> Mixer.toggleSolo "drums"
                        |> Mixer.soloedStems
                        |> Expect.equal []
            , test "soloing another replaces rather than adds" <|
                \_ ->
                    mixer
                        |> Mixer.toggleSolo "drums"
                        |> Mixer.toggleSolo "bass"
                        |> Mixer.soloedStems
                        |> Expect.equal [ "bass" ]
            , test "the solo is what a preview would carry" <|
                \_ ->
                    mixer
                        |> Mixer.toggleSolo "vocals"
                        |> Mixer.params
                        |> .stems
                        |> Expect.equal [ "vocals" ]
            ]
        , describe "the scrubber"
            [ test "starts at the top of the arc" <|
                \_ -> Mixer.params mixer |> .progress |> Expect.equal 0
            , test "carries the position a preview should render" <|
                \_ ->
                    mixer
                        |> Mixer.setProgress "0.5"
                        |> Mixer.params
                        |> .progress
                        |> Expect.within (Expect.Absolute 1.0e-9) 0.5
            , test "clamps above the end of the arc" <|
                \_ ->
                    -- `POST /api/preview` bounds progress to 0..1 and 422s
                    -- outside it.
                    mixer
                        |> Mixer.setProgress "1.4"
                        |> .progress
                        |> Expect.equal 1
            , test "clamps below the start" <|
                \_ ->
                    mixer |> Mixer.setProgress "-2" |> .progress |> Expect.equal 0
            , test "a value that is not a number leaves the position alone" <|
                \_ ->
                    mixer
                        |> Mixer.setProgress "0.5"
                        |> Mixer.setProgress ""
                        |> .progress
                        |> Expect.within (Expect.Absolute 1.0e-9) 0.5
            ]
        , describe "opening it"
            [ test "asks for one preview and waits" <|
                \_ -> phase opened.preview |> Expect.equal "Warming"
            , test "which is not yet playable, so the controls are inert" <|
                \_ -> Preview.isPlayable opened.preview |> Expect.equal False
            , test "at the top of the arc, which is what master_gain calibrates from" <|
                \_ ->
                    opened.mixer
                        |> Maybe.map (Mixer.params >> .progress)
                        |> Expect.equal (Just 0)
            , test "with a row per separated stem" <|
                \_ ->
                    opened.mixer
                        |> Maybe.map (.config >> .stems >> List.map .name)
                        |> Expect.equal (Just [ "vocals", "drums", "bass" ])
            , test "not at all when the song has no stems yet" <|
                \_ ->
                    onSong { song | stems = [], separationStatus = Api.NotSeparated }
                        |> step Main.OpenMixer
                        |> .mixer
                        |> Expect.equal Nothing
            , test "not at all before the schema its controls come from arrives" <|
                \_ ->
                    { fresh | selectedSongId = Just "song-1", currentSong = Just song }
                        |> step Main.OpenMixer
                        |> .mixer
                        |> Expect.equal Nothing
            ]
        , describe "while it is preparing"
            [ test "a control change sends nothing" <|
                \_ ->
                    opened
                        |> step (Main.ProgressChanged "0.5")
                        |> .preview
                        |> phase
                        |> Expect.equal "Warming"
            , test "and a control change against a cold session sends nothing either" <|
                \_ ->
                    { opened | preview = Preview.Cold }
                        |> step (Main.ProgressChanged "0.5")
                        |> .preview
                        |> phase
                        |> Expect.equal "Cold"
            , test "though the control itself still moves" <|
                \_ ->
                    -- `arcPanel` does not render the scrubber at all while the
                    -- session is not playable, so nothing can arrive here from
                    -- the mixer's own view. The model does not depend on that:
                    -- what matters is that a position arriving anyway is kept
                    -- rather than discarded, so the next preview is of where
                    -- the scrubber actually is.
                    { opened | preview = Preview.Cold }
                        |> step (Main.ProgressChanged "0.5")
                        |> .mixer
                        |> Maybe.map .progress
                        |> Expect.equal (Just 0.5)
            ]
        , describe "when the opening preview fails"
            [ test "the mixer does not become playable" <|
                \_ ->
                    -- The one thing that establishes there is anything to play
                    -- did not come back. Going Idle here would replace the
                    -- preparing panel with a live scrubber and enabled sliders
                    -- over silence, which is the promise "controls are inert
                    -- until then" makes and this would break.
                    opened
                        |> step (Main.PreviewFailed "server answered 500")
                        |> .preview
                        |> Preview.isPlayable
                        |> Expect.equal False
            , test "and goes back to cold rather than sitting in Warming" <|
                \_ ->
                    -- Warming would be a dead end: `request` refuses there, so
                    -- no control could ever start anything again.
                    opened
                        |> step (Main.PreviewFailed "server answered 500")
                        |> .preview
                        |> phase
                        |> Expect.equal "Cold"
            , test "and says what happened" <|
                \_ ->
                    opened
                        |> step (Main.PreviewFailed "server answered 500")
                        |> .previewError
                        |> Expect.equal (Just "server answered 500")
            , test "retrying opens it again rather than doing nothing" <|
                \_ ->
                    opened
                        |> step (Main.PreviewFailed "server answered 500")
                        |> step Main.RetryPreview
                        |> .preview
                        |> phase
                        |> Expect.equal "Warming"
            , test "and clears the error while that attempt is in flight" <|
                \_ ->
                    opened
                        |> step (Main.PreviewFailed "server answered 500")
                        |> step Main.RetryPreview
                        |> .previewError
                        |> Expect.equal Nothing
            , test "a retry that succeeds leaves it playable" <|
                \_ ->
                    opened
                        |> step (Main.PreviewFailed "server answered 500")
                        |> step Main.RetryPreview
                        |> step (Main.PreviewPlaying (Just 12.5))
                        |> .preview
                        |> Preview.isPlayable
                        |> Expect.equal True
            ]
        , describe "once the first preview has come back"
            [ test "it is playable" <|
                \_ -> Preview.isPlayable warm.preview |> Expect.equal True
            , test "and says how long the loop is" <|
                \_ -> warm.loopSeconds |> Expect.equal (Just 12.5)
            , test "a control change goes out immediately" <|
                \_ ->
                    warm
                        |> step (Main.ProgressChanged "0.5")
                        |> .preview
                        |> phase
                        |> Expect.equal "InFlight"
            , test "and a second one waits rather than queueing behind it" <|
                \_ ->
                    warm
                        |> step (Main.ProgressChanged "0.5")
                        |> step (Main.ProgressChanged "0.6")
                        |> step (Main.ProgressChanged "0.7")
                        |> .preview
                        |> phase
                        |> Expect.equal "Queued"
            , test "the waiting one goes as soon as the first returns" <|
                \_ ->
                    warm
                        |> step (Main.ProgressChanged "0.5")
                        |> step (Main.ProgressChanged "0.7")
                        |> step (Main.PreviewPlaying (Just 12.5))
                        |> .preview
                        |> phase
                        |> Expect.equal "InFlight"
            , test "a failure frees the slot as surely as a success" <|
                \_ ->
                    -- Once the session is known to be playable, a failure at
                    -- one scrubber position says nothing about the next.
                    -- Anything else strands the state machine in `InFlight`
                    -- and the scrubber stops responding for the rest of the
                    -- session.
                    warm
                        |> step (Main.ProgressChanged "0.5")
                        |> step (Main.PreviewFailed "server answered 500")
                        |> .preview
                        |> phase
                        |> Expect.equal "Idle"
            , test "and says so" <|
                \_ ->
                    warm
                        |> step (Main.PreviewFailed "server answered 500")
                        |> .previewError
                        |> Expect.equal (Just "server answered 500")
            , test "a preview that plays clears the last failure" <|
                \_ ->
                    warm
                        |> step (Main.PreviewFailed "server answered 500")
                        |> step (Main.PreviewPlaying (Just 9.0))
                        |> .previewError
                        |> Expect.equal Nothing
            ]
        , describe "leaving it"
            [ test "closing it stops the audio and forgets the mixer" <|
                \_ ->
                    let
                        after =
                            step Main.CloseMixer warm
                    in
                    Expect.all
                        [ \m -> Expect.equal Nothing m.mixer
                        , \m -> Expect.equal "Cold" (phase m.preview)
                        , \m -> Expect.equal (Just "song-1") m.selectedSongId
                        ]
                        after
            , test "going back to the library does too" <|
                \_ ->
                    let
                        after =
                            step Main.BackToLibrary warm
                    in
                    Expect.all
                        [ \m -> Expect.equal Nothing m.mixer
                        , \m -> Expect.equal "Cold" (phase m.preview)
                        ]
                        after
            , test "so does opening another song" <|
                \_ ->
                    let
                        after =
                            step (Main.SelectedSong "song-2") warm
                    in
                    Expect.all
                        [ \m -> Expect.equal Nothing m.mixer
                        , \m -> Expect.equal "Cold" (phase m.preview)
                        ]
                        after
            , test "and a preview arriving afterwards changes nothing" <|
                \_ ->
                    -- `stopPreview` tells `audio.js` to forget the request, so
                    -- this should not happen; if it does, it must not move a
                    -- state machine that has been reset.
                    warm
                        |> step Main.CloseMixer
                        |> step (Main.PreviewPlaying (Just 9.0))
                        |> .preview
                        |> phase
                        |> Expect.equal "Cold"
            ]
        , describe "starting a render"
            [ describe "the pre-flight line"
                -- Two facts, and both of them read off the thing they are about
                -- rather than written into a fixed sentence. A hard-coded
                -- string would pass none of these.
                [ test "states how long the mix it is about to make will be" <|
                    \_ ->
                        Mixer.preflight True mixer
                            |> String.contains "20 min"
                            |> Expect.equal True
                , test "and follows the duration control rather than a default" <|
                    \_ ->
                        mixer
                            |> Mixer.setField Fixtures.schema
                                (Config.InSection "output" "duration_min")
                                "45"
                            |> Mixer.preflight True
                            |> String.contains "45 min"
                            |> Expect.equal True
                , test "says the stems are already there when they are" <|
                    \_ ->
                        Mixer.preflight True mixer
                            |> String.contains "already separated"
                            |> Expect.equal True
                , test "and that separation runs first when they are not" <|
                    \_ ->
                        Mixer.preflight False mixer
                            |> String.contains "not separated yet"
                            |> Expect.equal True
                , test "a config carrying no length says so rather than claiming zero" <|
                    \_ ->
                        -- `Config.set` drops a key it cannot parse, and absent
                        -- means "whatever the server decides" everywhere else
                        -- in this module. Rendering that as "0 min" would be
                        -- the screen inventing a length nobody stated.
                        mixer
                            |> Mixer.setField Fixtures.schema
                                (Config.InSection "output" "duration_min")
                                ""
                            |> Mixer.preflight True
                            |> String.contains "server defaults to"
                            |> Expect.equal True
                ]
            , describe "whether the button can be pressed"
                [ test "an ordinary mixer can" <|
                    \_ -> Mixer.renderBlock False mixer |> Expect.equal Nothing
                , test "not while a render POST is already in flight" <|
                    \_ -> Mixer.renderBlock True mixer |> Expect.notEqual Nothing
                , test "and not with every stem switched off" <|
                    \_ ->
                        everyStemOff.mixer
                            |> Maybe.map (Mixer.renderBlock False >> (/=) Nothing)
                            |> Expect.equal (Just True)
                , test "one stem left is not that state" <|
                    \_ ->
                        oneStemLeft.mixer
                            |> Maybe.map (Mixer.renderBlock False)
                            |> Expect.equal (Just Nothing)
                ]
            , describe "the config it would send"
                [ test "is the one the previews have been carrying" <|
                    \_ ->
                        warm
                            |> step (Main.FieldChanged (Config.InStem 1 "gain_db") "-6.5")
                            |> .mixer
                            |> Maybe.map
                                (Mixer.renderConfig
                                    >> Decode.decodeValue (stemField 1 "gain_db" Decode.float)
                                )
                            |> Expect.equal (Just (Ok -6.5))
                , test "with every stem in it, whatever is soloed" <|
                    \_ ->
                        -- A solo is a way to hear one stem while shaping it,
                        -- not a decision about the mix. `Mixer.params` carries
                        -- it in a field of its own for the preview; the config
                        -- a render is made from must not.
                        warm
                            |> step (Main.SoloToggled "drums")
                            |> .mixer
                            |> Maybe.map
                                (Mixer.renderConfig
                                    >> Decode.decodeValue
                                        (Decode.field "stems"
                                            (Decode.list (Decode.field "name" Decode.string))
                                        )
                                )
                            |> Expect.equal (Just (Ok [ "vocals", "drums", "bass" ]))
                ]
            , describe "through the button"
                [ test "pressing it puts a request in flight" <|
                    \_ ->
                        warm
                            |> step Main.RenderClicked
                            |> .startingRender
                            |> Expect.notEqual Nothing
                , test "even before the first preview has come back" <|
                    \_ ->
                        -- Deliberately not gated on the session being playable:
                        -- a render is server-side work, and a browser that
                        -- could not decode a preview WAV must not be the thing
                        -- that stops a mix being made at all.
                        opened
                            |> step Main.RenderClicked
                            |> .startingRender
                            |> Expect.notEqual Nothing
                , test "a second press while one is in flight issues nothing" <|
                    \_ ->
                        -- `POST /api/renders` submits unconditionally, so a
                        -- second click inside one round trip is a second mix
                        -- queued behind the first. `nextRequest` is the witness:
                        -- it moves once per issued request and nothing else
                        -- touches it here.
                        let
                            once =
                                step Main.RenderClicked warm
                        in
                        step Main.RenderClicked once
                            |> Expect.all
                                [ \m -> Expect.equal once.startingRender m.startingRender
                                , \m -> Expect.equal once.nextRequest m.nextRequest
                                ]
                , test "and with every stem switched off, nothing is sent" <|
                    \_ ->
                        everyStemOff
                            |> step Main.RenderClicked
                            |> .startingRender
                            |> Expect.equal Nothing
                ]
            , describe "when the server has taken it"
                [ test "the renders screen opens on the row it just made" <|
                    \_ ->
                        warm
                            |> step Main.RenderClicked
                            |> answered (Ok startedJob)
                            |> .renders
                            |> Expect.equal (Just Renders.Loading)
                , test "the mixer closes and the preview stops with it" <|
                    \_ ->
                        -- Not something this task chose: every door into the
                        -- renders screen goes through `leaveMixer`, because a
                        -- preview loops until told otherwise and one left
                        -- running under a screen with no transport is music
                        -- with no way to stop it.
                        warm
                            |> step Main.RenderClicked
                            |> answered (Ok startedJob)
                            |> Expect.all
                                [ \m -> Expect.equal Nothing m.mixer
                                , \m -> Expect.equal "Cold" (phase m.preview)
                                ]
                , test "and the queue screen is not left open underneath it" <|
                    \_ ->
                        warm
                            |> step Main.OpenQueue
                            |> step Main.OpenMixer
                            |> step Main.RenderClicked
                            |> answered (Ok startedJob)
                            |> .queue
                            |> Expect.equal Nothing
                , test "the button is free again" <|
                    \_ ->
                        warm
                            |> step Main.RenderClicked
                            |> answered (Ok startedJob)
                            |> .startingRender
                            |> Expect.equal Nothing
                ]
            , describe "when it is refused"
                [ test "the mixer stays where it was" <|
                    \_ ->
                        warm
                            |> step Main.RenderClicked
                            |> answered (Err (Http.BadStatus 400))
                            |> Expect.all
                                [ \m -> Expect.notEqual Nothing m.mixer
                                , \m -> Expect.equal Nothing m.renders
                                ]
                , test "and says why, where the button was" <|
                    \_ ->
                        warm
                            |> step Main.RenderClicked
                            |> answered (Err (Http.BadStatus 400))
                            |> .renderError
                            |> Expect.equal (Just "the server answered 400")
                , test "the button is free to try again" <|
                    \_ ->
                        warm
                            |> step Main.RenderClicked
                            |> answered (Err (Http.BadStatus 400))
                            |> .startingRender
                            |> Expect.equal Nothing
                , test "and pressing it again clears the last failure" <|
                    \_ ->
                        warm
                            |> step Main.RenderClicked
                            |> answered (Err (Http.BadStatus 400))
                            |> step Main.RenderClicked
                            |> .renderError
                            |> Expect.equal Nothing
                , test "leaving the mixer takes the failure with it" <|
                    \_ ->
                        -- Rather than keeping it to show under the *next* mixer
                        -- session, which would report a failure that has
                        -- nothing to do with the song then on screen.
                        warm
                            |> step Main.RenderClicked
                            |> answered (Err (Http.BadStatus 400))
                            |> step Main.CloseMixer
                            |> .renderError
                            |> Expect.equal Nothing
                ]
            , describe "a render in flight belongs to the song that asked for it"
                -- Every one of these was reachable while `startingRender` was a
                -- bare request id: a POST on song A was a fact about the
                -- application rather than about A, so every consequence landed
                -- on whichever song was open when the answer came back.
                [ test "another song's Render button is not waiting on it" <|
                    \_ ->
                        warm
                            |> step Main.RenderClicked
                            |> openSong songB
                            |> Main.renderStartingFor songB.id
                            |> Expect.equal False
                , test "and the song that asked still is" <|
                    \_ ->
                        -- The control for the assertion above: same model, same
                        -- question, a different song.
                        warm
                            |> step Main.RenderClicked
                            |> openSong songB
                            |> Main.renderStartingFor song.id
                            |> Expect.equal True
                , test "so that other song can start a render of its own" <|
                    \_ ->
                        warm
                            |> step Main.RenderClicked
                            |> openSong songB
                            |> step Main.RenderClicked
                            |> .startingRender
                            |> Maybe.map .songId
                            |> Expect.equal (Just songB.id)
                , test "the answer does not close a different song's mixer" <|
                    \_ ->
                        warm
                            |> step Main.RenderClicked
                            |> openSong songB
                            |> answered (Ok startedJob)
                            |> Expect.all
                                [ \m -> Expect.notEqual Nothing m.mixer
                                , \m -> Expect.equal Nothing m.renders
                                , \m -> Expect.equal "Warming" (phase m.preview)
                                ]
                , test "nor reports its failure on that mixer" <|
                    \_ ->
                        warm
                            |> step Main.RenderClicked
                            |> openSong songB
                            |> answered (Err (Http.BadStatus 500))
                            |> .renderError
                            |> Expect.equal Nothing
                , test "a failure with no mixer open is not written at all" <|
                    \_ ->
                        -- Asserted at the moment of the write rather than after
                        -- the next screen opens, because `OpenMixer` also
                        -- clears the field and would mask this. The guard at
                        -- the write is what makes the message impossible to
                        -- misplace; the clear on entry is only belt and braces.
                        warm
                            |> step Main.RenderClicked
                            |> step Main.BackToLibrary
                            |> answered (Err (Http.BadStatus 500))
                            |> .renderError
                            |> Expect.equal Nothing
                , test "so no later mixer inherits it" <|
                    \_ ->
                        -- The reported bug, end to end: press Render, walk back
                        -- to the library, let a 500 arrive, open a different
                        -- song's mixer. It used to greet you with "the server
                        -- answered 500" about a song you had left.
                        warm
                            |> step Main.RenderClicked
                            |> step Main.BackToLibrary
                            |> answered (Err (Http.BadStatus 500))
                            |> openSong songB
                            |> .renderError
                            |> Expect.equal Nothing
                , test "but leaving only the mixer still lands the success on renders" <|
                    \_ ->
                        -- The half that must survive the fix: closing the mixer
                        -- is not leaving the song, and the click asked to go to
                        -- the renders screen.
                        warm
                            |> step Main.RenderClicked
                            |> step Main.CloseMixer
                            |> answered (Ok startedJob)
                            |> .renders
                            |> Expect.equal (Just Renders.Loading)
                ]
            , describe "the panel as it renders"
                -- Everything above tests functions that decide. These test that
                -- the screen calls them: delete the call and the decision is
                -- still perfect and still invisible, which is the shape of the
                -- failure this project already shipped once with
                -- `.progress-fill`.
                [ test "the pre-flight line is on the screen" <|
                    \_ ->
                        warm
                            |> screen
                            |> Query.find [ Selector.class "render-start" ]
                            |> Query.has [ Selector.text "20 min mix" ]
                , test "a long source puts the warning on it" <|
                    \_ ->
                        longWarm
                            |> screen
                            |> Query.find [ Selector.class "warn" ]
                            |> Query.has [ Selector.text "roughly 70 minutes" ]
                , test "and an ordinary one does not" <|
                    \_ ->
                        warm
                            |> screen
                            |> Query.findAll [ Selector.class "warn" ]
                            |> Query.count (Expect.equal 0)
                , test "the button is live when there is something to render" <|
                    \_ ->
                        warm
                            |> screen
                            |> Query.find [ Selector.class "render-go" ]
                            |> Query.has [ Selector.disabled False ]
                , test "and disabled when there is not" <|
                    \_ ->
                        everyStemOff
                            |> screen
                            |> Query.find [ Selector.class "render-go" ]
                            |> Query.has [ Selector.disabled True ]
                , test "and says why, under it" <|
                    \_ ->
                        everyStemOff
                            |> screen
                            |> Query.find [ Selector.class "render-start" ]
                            |> Query.has [ Selector.text "nothing to render" ]
                , test "clicking it asks Main for a render" <|
                    \_ ->
                        warm
                            |> screen
                            |> Query.find [ Selector.class "render-go" ]
                            |> Event.simulate Event.click
                            |> Event.expect Main.RenderClicked
                ]
            , describe "an answer nobody is waiting for"
                [ test "does not open the renders screen" <|
                    \_ ->
                        -- Nothing issues a second POST while one is in flight,
                        -- so this should not happen; if it does, it must not
                        -- navigate a screen that never asked to move.
                        warm
                            |> step (Main.RenderStarted 4321 (Ok startedJob))
                            |> .renders
                            |> Expect.equal Nothing
                , test "and does not write an error nobody caused" <|
                    \_ ->
                        warm
                            |> step (Main.RenderStarted 4321 (Err Http.NetworkError))
                            |> .renderError
                            |> Expect.equal Nothing
                ]
            ]
        ]


fresh : Main.Model
fresh =
    Tuple.first (Main.init ())
