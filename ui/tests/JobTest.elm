module JobTest exposing (suite)

import Api
import Expect
import Main
import Test exposing (Test, describe, test)


aJob : String -> Api.JobStatus -> Float -> Api.Job
aJob id status fraction =
    { id = id
    , kind = "separate"
    , status = status
    , fraction = fraction
    , message = "working"
    , songId = Just "song-1"
    }


suite : Test
suite =
    describe "Main's job state machine"
        [ describe "jobOutcome"
            [ test "an event for the tracked job updates it" <|
                \_ ->
                    Main.jobOutcome
                        (aJob "j1" Api.Running 0.5)
                        (Main.Watching (aJob "j1" Api.Queued 0.0))
                        |> Expect.equal (Main.Tracking (aJob "j1" Api.Running 0.5))
            , test "an event for a different job is ignored" <|
                \_ ->
                    Main.jobOutcome
                        (aJob "other" Api.Running 0.9)
                        (Main.Watching (aJob "j1" Api.Running 0.1))
                        |> Expect.equal Main.Ignored
            , test "an event arriving with nothing tracked is ignored" <|
                \_ ->
                    Main.jobOutcome (aJob "j1" Api.Running 0.5) Main.Idle
                        |> Expect.equal Main.Ignored
            , test "an event arriving before the POST has answered is ignored" <|
                \_ ->
                    Main.jobOutcome
                        (aJob "j1" Api.Running 0.5)
                        (Main.Starting { request = 3, songId = "song-1" })
                        |> Expect.equal Main.Ignored
            , test "a terminal event finishes the watch" <|
                \_ ->
                    Main.jobOutcome
                        (aJob "j1" Api.Done 1.0)
                        (Main.Watching (aJob "j1" Api.Running 0.8))
                        |> Expect.equal (Main.Finished (aJob "j1" Api.Done 1.0))
            , test "a cancelled event finishes the watch too" <|
                \_ ->
                    Main.jobOutcome
                        (aJob "j1" Api.Cancelled 0.4)
                        (Main.Watching (aJob "j1" Api.Running 0.4))
                        |> Expect.equal (Main.Finished (aJob "j1" Api.Cancelled 0.4))
            , test "a failure finishes the watch and keeps the reason" <|
                \_ ->
                    case
                        Main.jobOutcome
                            (aJob "j1" (Api.Failed "disk full") 0.6)
                            (Main.Watching (aJob "j1" Api.Running 0.6))
                    of
                        Main.Finished finished ->
                            Expect.equal (Api.Failed "disk full") finished.status

                        other ->
                            Expect.fail
                                ("expected Finished, got " ++ Debug.toString other)
            ]
        , describe "separationOnSelect"
            [ test "a watch for the song being opened is kept, and its stream left alone" <|
                \_ ->
                    Main.separationOnSelect "song-1"
                        (Main.Watching (aJob "j1" Api.Running 0.3))
                        |> Expect.equal
                            { separation = Main.Watching (aJob "j1" Api.Running 0.3)
                            , stopWatching = Nothing
                            }
            , test "a watch for a different song is dropped and its stream closed" <|
                \_ ->
                    Main.separationOnSelect "song-2"
                        (Main.Watching (aJob "j1" Api.Running 0.3))
                        |> Expect.equal
                            { separation = Main.Idle, stopWatching = Just "j1" }
            , test "a job with no song at all is dropped and its stream closed" <|
                \_ ->
                    let
                        orphan =
                            aJob "j1" Api.Running 0.3
                    in
                    Main.separationOnSelect "song-1" (Main.Watching { orphan | songId = Nothing })
                        |> Expect.equal
                            { separation = Main.Idle, stopWatching = Just "j1" }
            , test "a POST still in flight for this song is kept" <|
                \_ ->
                    Main.separationOnSelect "song-1"
                        (Main.Starting { request = 7, songId = "song-1" })
                        |> Expect.equal
                            { separation = Main.Starting { request = 7, songId = "song-1" }
                            , stopWatching = Nothing
                            }
            , test "a POST in flight for another song is dropped, with no stream to close" <|
                \_ ->
                    Main.separationOnSelect "song-2"
                        (Main.Starting { request = 7, songId = "song-1" })
                        |> Expect.equal
                            { separation = Main.Idle, stopWatching = Nothing }
            , test "idle stays idle" <|
                \_ ->
                    Main.separationOnSelect "song-1" Main.Idle
                        |> Expect.equal
                            { separation = Main.Idle, stopWatching = Nothing }
            ]
        , describe "streamFailureFor"
            [ test "the stream we are watching dying is a real loss" <|
                \_ ->
                    Main.streamFailureFor "j1" (Main.Watching (aJob "j1" Api.Running 0.2))
                        |> Expect.equal (Main.StreamLost "j1")
            , test "some other job's stream dying is not our problem" <|
                \_ ->
                    Main.streamFailureFor "j2" (Main.Watching (aJob "j1" Api.Running 0.2))
                        |> Expect.equal Main.StreamIrrelevant
            , test "a stream dying after we stopped watching is the normal close" <|
                \_ ->
                    Main.streamFailureFor "j1" Main.Idle
                        |> Expect.equal Main.StreamIrrelevant
            ]
        ]
