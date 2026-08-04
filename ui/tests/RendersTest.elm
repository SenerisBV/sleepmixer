module RendersTest exposing (suite)

{-| The decisions on the renders screen, which are all joins and summaries.

The view itself is markup and `elm-test` does not look at it — the classes it
emits are checked from the Python side by
`tests/test_static_bundle.py::test_every_class_the_views_emit_has_a_rule_on_the_page`.
What is worth testing here is everything the view *asks* before it draws:
which song a render belongs to, what distinguishes one render of that song from
another, which job is producing it, and what to say when the answer is not
recorded anywhere.
-}

import Api
import Expect
import Http
import Json.Decode as Decode
import Json.Encode as Encode
import Page.Renders as Renders
import Test exposing (Test, describe, test)


{-| A config as the server stores it: a real JSON object, not a string of JSON.

A fixture that is not JSON becomes a loud string rather than `null`, so a typo
in a test shows up as a wrong summary naming itself rather than as a passing
"not recorded".
-}
configOf : String -> Decode.Value
configOf raw =
    case Decode.decodeString Decode.value raw of
        Ok value ->
            value

        Err _ ->
            Encode.string ("this test fixture is not JSON: " ++ raw)


aSong : String -> String -> Api.Song
aSong id title =
    { id = id
    , path = "/music/" ++ id ++ ".flac"
    , title = title
    , durationS = 214.5
    , sampleRate = 44100
    , separationStatus = Api.Separated
    , stems = [ "bass", "drums", "other", "vocals" ]
    , addedAt = "2026-08-04T10:00:00+00:00"
    }


{-| A finished render, to be adjusted per test by record update.
-}
aRender : String -> String -> String -> Api.Render
aRender id songId config =
    { id = id
    , songId = songId
    , status = Api.RenderDone
    , path = "/tmp/data/renders/" ++ id ++ ".wav"
    , durationMin = Just 20.0
    , config = configOf config
    , createdAt = "2026-08-04T21:03:35.473657+00:00"
    }


aJob : String -> String -> String -> Api.Job
aJob id songId createdAt =
    { id = id
    , kind = "render"
    , status = Api.Running
    , fraction = 0.4
    , message = "rendering"
    , songId = Just songId
    , createdAt = createdAt
    }


{-| Two stems on, drums off, each decaying to a different lowpass endpoint —
the shape `Config.encode` produces and `MixConfig.from_dict` reads back.
-}
vocalsAndBass : String
vocalsAndBass =
    """
    { "output": {"duration_min": 30.0}
    , "stems":
        [ {"name": "vocals", "enabled": true,
           "decay": {"enabled": true, "lowpass_end_hz": 2200.0}}
        , {"name": "bass", "enabled": true,
           "decay": {"enabled": true, "lowpass_end_hz": 1600.0}}
        , {"name": "drums", "enabled": false,
           "decay": {"enabled": true, "lowpass_end_hz": 1600.0}}
        ]
    }
    """


vocalsOnly : String
vocalsOnly =
    """
    { "output": {"duration_min": 30.0}
    , "stems":
        [ {"name": "vocals", "enabled": true,
           "decay": {"enabled": true, "lowpass_end_hz": 2200.0}}
        , {"name": "bass", "enabled": false,
           "decay": {"enabled": true, "lowpass_end_hz": 1600.0}}
        , {"name": "drums", "enabled": false,
           "decay": {"enabled": true, "lowpass_end_hz": 1600.0}}
        ]
    }
    """


suite : Test
suite =
    describe "Page.Renders"
        [ describe "the song a render came from"
            [ test "a render whose song is still in the library is listed under its title" <|
                \_ ->
                    Renders.titleFor [ aSong "s2" "Other", aSong "s1" "Nocturne" ] "s1"
                        |> Expect.equal "Nocturne"
            , test "a render whose song has been removed shows its id rather than nothing" <|
                \_ ->
                    Renders.titleFor [ aSong "s1" "Nocturne" ] "s-deleted"
                        |> Expect.equal "s-deleted"
            , test "a render listed before the library has loaded still shows something" <|
                \_ ->
                    Renders.titleFor [] "s1"
                        |> Expect.equal "s1"
            ]
        , describe "what one render of a song says about itself that another does not"
            [ test "two renders of the same song with different stems summarise differently" <|
                \_ ->
                    let
                        both =
                            Renders.summarise (configOf vocalsAndBass)

                        one =
                            Renders.summarise (configOf vocalsOnly)
                    in
                    Expect.all
                        [ \_ -> Expect.notEqual both one
                        , \_ -> Expect.equal True (String.contains "bass" both.stems)
                        , \_ -> Expect.equal False (String.contains "bass" one.stems)
                        ]
                        ()
            , test "the summary states the mix length the config asked for" <|
                \_ ->
                    (Renders.summarise (configOf vocalsAndBass)).length
                        |> Expect.equal "30 min"
            , test "a stem switched off is not listed as one that played" <|
                \_ ->
                    (Renders.summarise (configOf vocalsAndBass)).stems
                        |> Expect.equal "vocals · bass"
            , test "the decay endpoint spans the stems that decay rather than picking one" <|
                \_ ->
                    (Renders.summarise (configOf vocalsAndBass)).decay
                        |> Expect.equal "decays to 1.6–2.2 kHz"
            , test "an empty config admits it recorded nothing rather than claiming defaults" <|
                \_ ->
                    let
                        summary =
                            Renders.summarise (configOf "{}")
                    in
                    Expect.all
                        [ \s -> Expect.equal True (String.contains "not recorded" s.length)
                        , \s -> Expect.equal True (String.contains "not recorded" s.stems)
                        , \s -> Expect.equal True (String.contains "not recorded" s.decay)
                        ]
                        summary
            , test "a config that records the length but no stems says so for the stems only" <|
                \_ ->
                    -- The shape a render started through the API carries: a
                    -- partial override, with MixConfig's own stem list applied
                    -- server-side where nothing here can see it.
                    let
                        summary =
                            Renders.summarise
                                (configOf """{"output": {"duration_min": 0.05}}""")
                    in
                    Expect.all
                        [ \s -> Expect.equal "3 s" s.length
                        , \s -> Expect.equal True (String.contains "not recorded" s.stems)
                        ]
                        summary
            ]
        , describe "how long the finished file is"
            [ test "a render with no duration recorded does not claim to be zero minutes" <|
                \_ ->
                    Renders.durationLabel Nothing
                        |> Expect.all
                            [ Expect.notEqual "0 minutes"
                            , \label -> Expect.equal False (String.contains "0" label)
                            , \label -> Expect.equal True (String.contains "not recorded" label)
                            ]
            , test "a finished render states its length in minutes" <|
                \_ ->
                    Renders.durationLabel (Just 30.0) |> Expect.equal "30 min"
            , test "a render shorter than a minute is stated in seconds rather than rounded to nothing" <|
                \_ ->
                    Renders.durationLabel (Just 0.05) |> Expect.equal "3 s"
            ]
        , describe "the job behind a render"
            [ test "a render is paired with the job submitted just after its row was written" <|
                \_ ->
                    let
                        first =
                            { earlier | createdAt = "2026-08-04T21:03:17.582197+00:00" }

                        earlier =
                            aRender "r1" "s1" "{}"

                        second =
                            { earlier | id = "r2", createdAt = "2026-08-04T21:03:35.473657+00:00" }

                        jobs =
                            [ aJob "j2" "s1" "2026-08-04T21:03:35.501000+00:00"
                            , aJob "j1" "s1" "2026-08-04T21:03:17.601000+00:00"
                            ]
                    in
                    Expect.all
                        [ \_ -> Expect.equal (Just "j1") (Maybe.map .id (Renders.jobFor jobs first))
                        , \_ -> Expect.equal (Just "j2") (Maybe.map .id (Renders.jobFor jobs second))
                        ]
                        ()
            , test "a separation job for the same song is not mistaken for the render's" <|
                \_ ->
                    let
                        separation =
                            { job | kind = "separate" }

                        job =
                            aJob "j1" "s1" "2026-08-04T21:03:35.501000+00:00"
                    in
                    Renders.jobFor [ separation ] (aRender "r1" "s1" "{}")
                        |> Expect.equal Nothing
            , test "the job watched for progress is the running one, not merely the first" <|
                \_ ->
                    let
                        queued =
                            { running
                                | id = "j2"
                                , status = Api.Queued
                                , createdAt = "2026-08-04T21:03:17.601000+00:00"
                            }

                        running =
                            aJob "j1" "s1" "2026-08-04T21:03:35.501000+00:00"
                    in
                    Renders.liveRenderJob [ queued, running ]
                        |> Maybe.map .id
                        |> Expect.equal (Just "j1")
            , test "a finished render job is not watched" <|
                \_ ->
                    Renders.liveRenderJob
                        [ { sampleJob | status = Api.Done } ]
                        |> Expect.equal Nothing
            , test "a fresher event replaces the polled copy of the same job" <|
                \_ ->
                    let
                        fresher =
                            { sampleJob | fraction = 0.9 }
                    in
                    Renders.replaceJob fresher [ aJob "j0" "s1" "x", sampleJob ]
                        |> List.map .fraction
                        |> Expect.equal [ 0.4, 0.9 ]
            , test "an event for a job the poll never mentioned is kept rather than dropped" <|
                \_ ->
                    Renders.replaceJob sampleJob []
                        |> List.map .id
                        |> Expect.equal [ "j1" ]
            ]
        , describe "when a render ended badly"
            [ test "a failed render shows the reason its job recorded" <|
                \_ ->
                    Renders.reasonFor Api.RenderFailed
                        (Just { sampleJob | status = Api.Failed "LibsndfileError: Permission denied" })
                        |> String.contains "Permission denied"
                        |> Expect.equal True
            , test "a failed render whose job is gone says nobody recorded why, rather than inventing one" <|
                \_ ->
                    Renders.reasonFor Api.RenderFailed Nothing
                        |> Expect.all
                            [ \reason -> Expect.equal True (String.contains "ailed" reason)
                            , \reason -> Expect.notEqual "" reason
                            ]
            , test "a cancelled render says its partial file is gone" <|
                \_ ->
                    Renders.reasonFor Api.RenderCancelled Nothing
                        |> String.contains "Cancelled"
                        |> Expect.equal True
            ]
        , describe "deleting"
            [ test "a delete refused while the render is still running says to cancel it first" <|
                \_ ->
                    Renders.deleteMessage (Http.BadStatus 409) "the server answered 409"
                        |> String.contains "ancel"
                        |> Expect.equal True
            , test "any other refusal carries the detail rather than guessing at it" <|
                \_ ->
                    Renders.deleteMessage Http.NetworkError "could not reach the server"
                        |> String.contains "could not reach the server"
                        |> Expect.equal True
            ]
        , describe "the list itself"
            [ test "renders are listed newest first whatever order they arrived in" <|
                \_ ->
                    let
                        old =
                            { new | id = "old", createdAt = "2026-08-01T09:00:00+00:00" }

                        new =
                            aRender "new" "s1" "{}"
                    in
                    Renders.newestFirst [ old, new ]
                        |> List.map .id
                        |> Expect.equal [ "new", "old" ]
            , test "the timestamp is shortened to a minute rather than shown to the microsecond" <|
                \_ ->
                    Renders.momentOf "2026-08-04T21:03:35.473657+00:00"
                        |> Expect.equal "2026-08-04 21:03"
            , test "a timestamp in a shape we do not recognise is shown as it came" <|
                \_ ->
                    Renders.momentOf "sometime" |> Expect.equal "sometime"
            , test "the audition and download point at the render's own audio route" <|
                \_ ->
                    Renders.audioUrl "f591fb37"
                        |> Expect.equal "/api/renders/f591fb37/audio"
            ]
        ]


sampleJob : Api.Job
sampleJob =
    aJob "j1" "s1" "2026-08-04T21:03:35.501000+00:00"
