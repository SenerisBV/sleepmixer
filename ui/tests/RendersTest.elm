module RendersTest exposing (suite)

{-| The decisions on the renders screen, which are mostly joins and summaries.

Most of the view is markup, and the classes it emits are checked from the
Python side by
`tests/test_static_bundle.py::test_every_class_the_views_emit_has_a_rule_on_the_page`.
What is worth testing here is everything the view *asks* before it draws:
which song a render belongs to, what distinguishes one render of that song from
another, which job is producing it, and what to say when the answer is not
recorded anywhere.

One thing on this screen is not a summary, though, and it is the only control
here that can destroy something: **Cancel**. `jobFor` is tested in isolation
below and cannot see whether the button is actually given the job it returned —
swapping `config.onCancel aJob.id` for `liveRenderJob`'s id compiles, and
reinstates the Critical this screen was rewritten to remove: a dead row's
Cancel stopping the render that is genuinely in flight, with `abandon_render`
deleting its file on the way out. So that one wiring is asserted through the
real view, and through `Main.view` rather than a hand-built page config, for
the reason `MixerTest` gives — a config written here would prove the markup and
nothing about what `Main` hands it.
-}

import Api
import Expect
import Http
import Json.Decode as Decode
import Json.Encode as Encode
import Main
import Page.Library as Library
import Page.Renders as Renders
import Test exposing (Test, describe, test)
import Test.Html.Event as Event
import Test.Html.Query as Query
import Test.Html.Selector as Selector


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
    , lastPresetId = Nothing
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


aJob : String -> String -> Maybe String -> String -> Api.Job
aJob id songId renderId createdAt =
    { id = id
    , kind = "render"
    , status = Api.Running
    , fraction = 0.4
    , message = "rendering"
    , songId = Just songId
    , renderId = renderId
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
            , test "a switched-off stem's decay endpoint is not part of the mix's" <|
                \_ ->
                    -- `vocalsOnly` has vocals on at 2200 Hz, with bass and drums
                    -- switched off at 1600 Hz. Nothing audible in that mix ever
                    -- reaches 1.6 kHz, and the row used to say it did.
                    (Renders.summarise (configOf vocalsOnly)).decay
                        |> Expect.all
                            [ Expect.equal "decays to 2.2 kHz"
                            , \decay -> Expect.equal False (String.contains "1.6" decay)
                            ]
            , test "a mix whose audible stems all have decay off claims none, however the silent ones decay" <|
                \_ ->
                    Renders.summarise
                        (configOf """
                        { "stems":
                            [ {"name": "vocals", "enabled": true,
                               "decay": {"enabled": false, "lowpass_end_hz": 2200.0}}
                            , {"name": "bass", "enabled": false,
                               "decay": {"enabled": true, "lowpass_end_hz": 1600.0}}
                            ]
                        }
                        """)
                        |> .decay
                        |> Expect.equal "no decay"
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
            [ test "a render is paired with the job carrying its own id" <|
                \_ ->
                    let
                        first =
                            aRender "r1" "s1" "{}"

                        second =
                            { first | id = "r2" }

                        jobs =
                            [ aJob "j2" "s1" (Just "r2") "2026-08-04T21:03:35.501000+00:00"
                            , aJob "j1" "s1" (Just "r1") "2026-08-04T21:03:17.601000+00:00"
                            ]
                    in
                    Expect.all
                        [ \_ -> Expect.equal (Just "j1") (Maybe.map .id (Renders.jobFor jobs first))
                        , \_ -> Expect.equal (Just "j2") (Maybe.map .id (Renders.jobFor jobs second))
                        ]
                        ()
            , test "a render stranded by a restart is paired with nothing, not with the next render's job" <|
                \_ ->
                    -- The bug this pairing exists to make impossible: jobs live
                    -- in memory and renders in SQLite, so a restart leaves a
                    -- render at `running` with no job of its own. Paired by song
                    -- and time it took the *next* render's job, drew that
                    -- render's progress, and put that render's job id on its
                    -- Cancel button — so cancelling the dead row killed the live
                    -- one and deleted its file.
                    let
                        stranded =
                            { id = "r-stranded"
                            , songId = "s1"
                            , status = Api.RenderRunning
                            , path = "/tmp/data/renders/r-stranded.wav"
                            , durationMin = Nothing
                            , config = configOf "{}"
                            , createdAt = "2026-08-01T09:00:00+00:00"
                            }

                        liveJob =
                            aJob "j-live" "s1" (Just "r-new") "2026-08-04T21:03:35.501000+00:00"
                    in
                    Renders.jobFor [ liveJob ] stranded
                        |> Expect.equal Nothing
            , test "a separation job for the same song is not mistaken for the render's" <|
                \_ ->
                    -- A separation carries the song id too, and no render id at
                    -- all — so matching on the render id excludes it by
                    -- construction rather than by a `kind` check that could be
                    -- forgotten.
                    let
                        separation =
                            { sampleJob | kind = "separate", renderId = Nothing }
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
                            aJob "j1" "s1" (Just "r1") "2026-08-04T21:03:35.501000+00:00"
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
                    Renders.replaceJob fresher
                        [ aJob "j0" "s1" (Just "r0") "x", sampleJob ]
                        |> List.map .fraction
                        |> Expect.equal [ 0.4, 0.9 ]
            , test "an event for a job the poll never mentioned is kept rather than dropped" <|
                \_ ->
                    Renders.replaceJob sampleJob []
                        |> List.map .id
                        |> Expect.equal [ "j1" ]
            , test "a poll landing after a stream event does not move the bar backwards" <|
                \_ ->
                    -- The poll is a round trip and the stream is a push, so a
                    -- snapshot taken at 30% can arrive after an event saying
                    -- 90%. Only the streamed job is held back; everything else
                    -- takes the polled value, which is fresher for it.
                    let
                        streamed =
                            { sampleJob | fraction = 0.9 }

                        polled =
                            [ { sampleJob | fraction = 0.3 }
                            , { sampleJob | id = "j2", fraction = 0.5 }
                            ]
                    in
                    Renders.keepStreamed (Just "j1") [ streamed ] polled
                        |> List.map .fraction
                        |> Expect.equal [ 0.9, 0.5 ]
            , test "with no stream open the poll is taken as it comes" <|
                \_ ->
                    let
                        polled =
                            [ { sampleJob | fraction = 0.3 } ]
                    in
                    Renders.keepStreamed Nothing [ { sampleJob | fraction = 0.9 } ] polled
                        |> List.map .fraction
                        |> Expect.equal [ 0.3 ]
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
                    -- Asserted as the whole sentence, because the thing being
                    -- tested is that it does not stop at "Failed." — the bare
                    -- word is the silence this module exists to refuse, and a
                    -- `String.contains "Failed"` assertion accepts it.
                    Renders.reasonFor Api.RenderFailed Nothing
                        |> Expect.equal
                            ("Failed. The reason was recorded on the job that ran it "
                                ++ "rather than on the render, and that job is no longer "
                                ++ "held — jobs live in memory and do not survive a restart."
                            )
            , test "a cancelled render says its partial file is gone" <|
                \_ ->
                    Renders.reasonFor Api.RenderCancelled Nothing
                        |> Expect.equal
                            ("Cancelled. The partial file was removed with it, so there is "
                                ++ "nothing here to play or download."
                            )
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
                    -- Both input orders, because the endpoint already answers
                    -- newest-first: a `List.reverse` with no sort passes against
                    -- the shuffled case alone and would list the real screen
                    -- oldest-first in production with this test green.
                    let
                        old =
                            { new | id = "old", createdAt = "2026-08-01T09:00:00+00:00" }

                        new =
                            aRender "new" "s1" "{}"
                    in
                    Expect.all
                        [ \_ -> Expect.equal [ "new", "old" ] (List.map .id (Renders.newestFirst [ old, new ]))
                        , \_ -> Expect.equal [ "new", "old" ] (List.map .id (Renders.newestFirst [ new, old ]))
                        ]
                        ()
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
        , describe "the Cancel button, through the whole application"
            -- The one control on this screen that can destroy something, and
            -- the one thing `jobFor` cannot vouch for. Two renders in flight at
            -- once is the only arrangement that can tell a correct wiring from
            -- a plausible wrong one: with a single render, its own job and "the
            -- live job" are the same value and every mutation passes.
            [ test "each row's Cancel carries that row's own job, not the live one" <|
                \_ ->
                    -- Reinstating the Critical — `config.onCancel
                    -- (liveRenderJob …)` — makes the queued row stop the
                    -- running render instead, and `abandon_render` deletes its
                    -- partial file. Both rows would look identical while doing
                    -- it, which is why this is asserted rather than read.
                    Expect.all
                        [ \_ ->
                            cancelOn 0
                                |> Event.expect (Main.CancelRenderClicked "job-for-queued")
                        , \_ ->
                            cancelOn 1
                                |> Event.expect (Main.CancelRenderClicked "job-for-running")
                        ]
                        ()
            , test "a row whose job the manager has forgotten offers no Cancel at all" <|
                \_ ->
                    -- The state a server restart leaves behind: the row is
                    -- still "running" in SQLite and the job is gone with the
                    -- process. A button here would have to guess which job it
                    -- meant, and guessing is what produced the Critical.
                    screen { twoInFlight | renderJobs = [] }
                        |> Query.findAll [ Selector.class "cancel" ]
                        |> Query.count (Expect.equal 0)
            ]
        ]


{-| Two renders genuinely in flight: one running, one waiting behind it.

Timestamps are set so `newestFirst` puts the queued one at index 0 and the
running one at index 1, which is also the truth — the queued render was asked
for later.
-}
twoInFlight : Main.Model
twoInFlight =
    let
        ( fresh, _ ) =
            Main.init ()

        running =
            { base
                | id = "render-running"
                , status = Api.RenderRunning
                , createdAt = "2026-08-04T21:00:00.000000+00:00"
            }

        queued =
            { base
                | id = "render-queued"
                , status = Api.RenderQueued
                , createdAt = "2026-08-04T21:05:00.000000+00:00"
            }

        base =
            aRender "r" "s1" "{}"
    in
    { fresh
        | library = Library.Loaded [ aSong "s1" "A Song" ]
        , renders = Just (Renders.Loaded [ running, queued ])
        , renderJobs =
            [ { runningJob | id = "job-for-running", renderId = Just "render-running" }
            , { runningJob
                | id = "job-for-queued"
                , renderId = Just "render-queued"
                , status = Api.Queued
                , createdAt = "2026-08-04T21:05:00.100000+00:00"
              }
            ]
    }


runningJob : Api.Job
runningJob =
    aJob "j" "s1" (Just "r") "2026-08-04T21:00:00.100000+00:00"


{-| The whole application as it would render, not a hand-built view config.
-}
screen : Main.Model -> Query.Single Main.Msg
screen model =
    Query.fromHtml (Main.view model)


cancelOn : Int -> Event.Event Main.Msg
cancelOn index =
    screen twoInFlight
        |> Query.findAll [ Selector.class "render-row" ]
        |> Query.index index
        |> Query.find [ Selector.class "cancel" ]
        |> Event.simulate Event.click


sampleJob : Api.Job
sampleJob =
    aJob "j1" "s1" (Just "r1") "2026-08-04T21:03:35.501000+00:00"
