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
    describe "Main.jobOutcome"
        [ test "an event for the tracked job updates it" <|
            \_ ->
                Main.jobOutcome
                    (aJob "j1" Api.Running 0.5)
                    (Just (aJob "j1" Api.Queued 0.0))
                    |> Expect.equal (Main.Tracking (aJob "j1" Api.Running 0.5))
        , test "an event for a different job is ignored" <|
            \_ ->
                Main.jobOutcome
                    (aJob "other" Api.Running 0.9)
                    (Just (aJob "j1" Api.Running 0.1))
                    |> Expect.equal Main.Ignored
        , test "an event arriving with nothing tracked is ignored" <|
            \_ ->
                Main.jobOutcome (aJob "j1" Api.Running 0.5) Nothing
                    |> Expect.equal Main.Ignored
        , test "a terminal event finishes the watch" <|
            \_ ->
                Main.jobOutcome
                    (aJob "j1" Api.Done 1.0)
                    (Just (aJob "j1" Api.Running 0.8))
                    |> Expect.equal (Main.Finished (aJob "j1" Api.Done 1.0))
        , test "a cancelled event finishes the watch too" <|
            \_ ->
                Main.jobOutcome
                    (aJob "j1" Api.Cancelled 0.4)
                    (Just (aJob "j1" Api.Running 0.4))
                    |> Expect.equal (Main.Finished (aJob "j1" Api.Cancelled 0.4))
        , test "a failure finishes the watch and keeps the reason" <|
            \_ ->
                case
                    Main.jobOutcome
                        (aJob "j1" (Api.Failed "disk full") 0.6)
                        (Just (aJob "j1" Api.Running 0.6))
                of
                    Main.Finished finished ->
                        Expect.equal (Api.Failed "disk full") finished.status

                    other ->
                        Expect.fail
                            ("expected Finished, got " ++ Debug.toString other)
        ]
