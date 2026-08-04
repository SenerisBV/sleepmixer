module UpdateTest exposing (suite)

{-| The parts of the job state machine that are not `jobOutcome`.

`jobOutcome` was extracted as a pure function precisely so it could be tested,
and it was the only piece that was — every bug the final review of this branch
found lived in the transitions around it. `Cmd` has no equality, so what these
assert is the *model* half of `update`; the command half is asserted through
the pure helpers `update` delegates to (`separationOnSelect` decides which
stream to close, `streamFailureFor` decides whether a dead stream matters),
which `JobTest` covers directly.
-}

import Api
import Expect
import Json.Decode
import Json.Encode
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
    , createdAt = "2026-08-04T21:03:17.584296+00:00"
    }


{-| A model as it stands with song-1 open and a separation running on it.
-}
watching : Api.Job -> Main.Model
watching job =
    let
        ( fresh, _ ) =
            Main.init ()
    in
    { fresh | selectedSongId = Just "song-1", separation = Main.Watching job }


step : Main.Msg -> Main.Model -> Main.Model
step msg model =
    Tuple.first (Main.update msg model)


suite : Test
suite =
    describe "Main.update"
        [ describe "selecting a song while a separation is running"
            [ test "keeps watching when it is the same song" <|
                \_ ->
                    watching (aJob "j1" Api.Running 0.4)
                        |> step (Main.SelectedSong "song-1")
                        |> .separation
                        |> Expect.equal (Main.Watching (aJob "j1" Api.Running 0.4))
            , test "drops the watch when it is a different song" <|
                \_ ->
                    watching (aJob "j1" Api.Running 0.4)
                        |> step (Main.SelectedSong "song-2")
                        |> .separation
                        |> Expect.equal Main.Idle
            , test "going back to the library leaves the separation running" <|
                \_ ->
                    watching (aJob "j1" Api.Running 0.4)
                        |> step Main.BackToLibrary
                        |> .separation
                        |> Expect.equal (Main.Watching (aJob "j1" Api.Running 0.4))
            , test "library and back again still knows about the job" <|
                \_ ->
                    watching (aJob "j1" Api.Running 0.4)
                        |> step Main.BackToLibrary
                        |> step (Main.SelectedSong "song-1")
                        |> .separation
                        |> Expect.equal (Main.Watching (aJob "j1" Api.Running 0.4))
            ]
        , describe "a terminal event"
            [ test "clears the separation while the song is on screen" <|
                \_ ->
                    watching (aJob "j1" Api.Running 0.4)
                        |> step (Main.JobEventReceived (Ok (aJob "j1" Api.Done 1.0)))
                        |> .separation
                        |> Expect.equal Main.Idle
            , test "clears the separation while the library is on screen" <|
                \_ ->
                    watching (aJob "j1" Api.Running 0.4)
                        |> step Main.BackToLibrary
                        |> step (Main.JobEventReceived (Ok (aJob "j1" Api.Done 1.0)))
                        |> .separation
                        |> Expect.equal Main.Idle
            , test "a non-terminal event keeps the watch and the new progress" <|
                \_ ->
                    watching (aJob "j1" Api.Running 0.0)
                        |> step (Main.JobEventReceived (Ok (aJob "j1" Api.Running 0.5)))
                        |> .separation
                        |> Expect.equal (Main.Watching (aJob "j1" Api.Running 0.5))
            , test "a re-fetch after finishing is not rejected by the request guard" <|
                \_ ->
                    let
                        after =
                            watching (aJob "j1" Api.Running 0.4)
                                |> step (Main.JobEventReceived (Ok (aJob "j1" Api.Done 1.0)))

                        separated =
                            { id = "song-1"
                            , path = "/tmp/a.wav"
                            , title = "A"
                            , durationS = 10.0
                            , sampleRate = 44100
                            , separationStatus = Api.Separated
                            , stems = [ "drums" ]
                            , addedAt = "2026-08-04"
                            }
                    in
                    after
                        |> step (Main.GotSongDetail after.songRequest (Ok separated))
                        |> .currentSong
                        |> Expect.equal (Just separated)
            ]
        , describe "a stream failure"
            [ test "ends the separation and says something actionable" <|
                \_ ->
                    let
                        after =
                            watching (aJob "j1" Api.Running 0.4)
                                |> step (Main.JobStreamFailed "j1")
                    in
                    Expect.all
                        [ \m -> Expect.equal Main.Idle m.separation
                        , \m -> Expect.notEqual Nothing m.eventError
                        , \m -> Expect.equal Nothing m.separateError
                        ]
                        after
            , test "a failure for a stream we are not watching changes nothing" <|
                \_ ->
                    let
                        before =
                            watching (aJob "j1" Api.Running 0.4)
                    in
                    step (Main.JobStreamFailed "j2") before
                        |> Expect.equal before
            ]
        , describe "a decode failure"
            [ test "ends the separation rather than leaving it running forever" <|
                \_ ->
                    watching (aJob "j1" Api.Running 0.4)
                        |> step (Main.JobEventReceived (Err badEvent))
                        |> .separation
                        |> Expect.equal Main.Idle
            , test "is reported as an event problem, not as a failure to start" <|
                \_ ->
                    let
                        after =
                            watching (aJob "j1" Api.Running 0.4)
                                |> step (Main.JobEventReceived (Err badEvent))
                    in
                    Expect.all
                        [ \m -> Expect.equal Nothing m.separateError
                        , \m -> Expect.notEqual Nothing m.eventError
                        ]
                        after
            ]
        , describe "a superseded separation POST"
            [ test "its response is dropped rather than adopted" <|
                \_ ->
                    let
                        ( fresh, _ ) =
                            Main.init ()

                        started =
                            { fresh | selectedSongId = Just "song-1" }
                                |> step (Main.SeparateClicked False)

                        elsewhere =
                            step (Main.SelectedSong "song-2") started

                        request =
                            case started.separation of
                                Main.Starting pending ->
                                    pending.request

                                _ ->
                                    -1
                    in
                    elsewhere
                        |> step (Main.Separated request (Ok (aJob "j1" Api.Queued 0.0)))
                        |> .separation
                        |> Expect.equal Main.Idle
            , test "a response for the POST still in flight is adopted" <|
                \_ ->
                    let
                        ( fresh, _ ) =
                            Main.init ()

                        started =
                            { fresh | selectedSongId = Just "song-1" }
                                |> step (Main.SeparateClicked False)

                        request =
                            case started.separation of
                                Main.Starting pending ->
                                    pending.request

                                _ ->
                                    -1
                    in
                    started
                        |> step (Main.Separated request (Ok (aJob "j1" Api.Queued 0.0)))
                        |> .separation
                        |> Expect.equal (Main.Watching (aJob "j1" Api.Queued 0.0))
            , test "a second click while one is in flight starts nothing new" <|
                \_ ->
                    let
                        ( fresh, _ ) =
                            Main.init ()

                        started =
                            { fresh | selectedSongId = Just "song-1" }
                                |> step (Main.SeparateClicked False)
                    in
                    step (Main.SeparateClicked False) started
                        |> Expect.equal started
            ]
        , describe "isSeparating"
            [ test "idle is not" <|
                \_ -> Main.isSeparating Main.Idle |> Expect.equal False
            , test "a POST in flight is" <|
                \_ ->
                    Main.isSeparating (Main.Starting { request = 1, songId = "song-1" })
                        |> Expect.equal True
            , test "a watched job is" <|
                \_ ->
                    Main.isSeparating (Main.Watching (aJob "j1" Api.Running 0.1))
                        |> Expect.equal True
            ]
        ]


{-| A `Decode.Error` to feed the decode-failure path, produced the same way the
subscription produces one: by running the real decoder over the wrong shape.
-}
badEvent : Json.Decode.Error
badEvent =
    case Json.Decode.decodeString Api.job "{\"id\":\"j1\"}" of
        Err err ->
            err

        Ok _ ->
            Json.Decode.Failure "the job decoder accepted a job with no status"
                (Json.Encode.string "unreachable")
