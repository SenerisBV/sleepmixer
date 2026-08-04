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
import Expect
import Fixtures
import Main
import Page.Mixer as Mixer
import Preview
import Test exposing (Test, describe, test)


song : Api.Song
song =
    { id = "song-1"
    , path = "/tmp/a.wav"
    , title = "A"
    , durationS = 210.0
    , sampleRate = 44100
    , separationStatus = Api.Separated
    , stems = [ "vocals", "drums", "bass" ]
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


suite : Test
suite =
    describe "the mixer"
        [ describe "solo"
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
        ]


fresh : Main.Model
fresh =
    Tuple.first (Main.init ())
