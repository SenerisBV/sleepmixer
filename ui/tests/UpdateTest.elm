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
    , renderId = Nothing
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


{-| A separation on song-1 *and* a render being watched at the same time — the
state that makes "which stream did this frame come from" a real question rather
than a rhetorical one.
-}
watchingBoth : Main.Model
watchingBoth =
    let
        base =
            watching (aJob "j1" Api.Running 0.4)
    in
    { base | watchedRender = Just "render-job" }


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
                        |> step (Main.JobEventReceived badEvent)
                        |> .separation
                        |> Expect.equal Main.Idle
            , test "is reported as an event problem, not as a failure to start" <|
                \_ ->
                    let
                        after =
                            watching (aJob "j1" Api.Running 0.4)
                                |> step (Main.JobEventReceived badEvent)
                    in
                    Expect.all
                        [ \m -> Expect.equal Nothing m.separateError
                        , \m -> Expect.notEqual Nothing m.eventError
                        ]
                        after
            , test "an unreadable frame from a render's stream leaves the separation alone" <|
                \_ ->
                    -- `jobEvent` is one channel for every stream, and this used
                    -- to end the separation whatever the frame's origin: a bad
                    -- frame on a render's stream reset a running separation to
                    -- Idle and closed its stream while Demucs carried on.
                    watchingBoth
                        |> step (Main.JobEventReceived badRenderEvent)
                        |> Expect.all
                            [ \m -> Expect.equal (Main.Watching (aJob "j1" Api.Running 0.4)) m.separation
                            , \m -> Expect.equal Nothing m.eventError
                            , \m -> Expect.equal Nothing m.watchedRender
                            , \m -> Expect.notEqual Nothing m.rendersProblem
                            ]
            , test "an unreadable frame is reported where the screen it belongs to can show it" <|
                \_ ->
                    -- `eventError` is rendered only by the song screen, so a
                    -- render's failure written there is a bar that silently
                    -- stops for someone on the renders screen.
                    watching (aJob "j1" Api.Running 0.4)
                        |> step (Main.JobEventReceived badEvent)
                        |> Expect.all
                            [ \m -> Expect.notEqual Nothing m.eventError
                            , \m -> Expect.equal Nothing m.rendersProblem
                            ]
            , test "an unreadable frame for neither watch changes nothing" <|
                \_ ->
                    step (Main.JobEventReceived badRenderEvent) (watching (aJob "j1" Api.Running 0.4))
                        |> Expect.equal (watching (aJob "j1" Api.Running 0.4))
            , test "an unreadable frame that does not say where it came from ends both watches" <|
                \_ ->
                    -- No id is no evidence, and both streams are the same shape
                    -- from the same server. Guessing is what the previous
                    -- version did — always in favour of the separation.
                    watchingBoth
                        |> step (Main.JobEventReceived anonymousBadEvent)
                        |> Expect.all
                            [ \m -> Expect.equal Main.Idle m.separation
                            , \m -> Expect.equal Nothing m.watchedRender
                            , \m -> Expect.notEqual Nothing m.eventError
                            , \m -> Expect.notEqual Nothing m.rendersProblem
                            ]
            , test "an anonymous frame with nothing being watched says nothing" <|
                \_ ->
                    let
                        ( fresh, _ ) =
                            Main.init ()
                    in
                    step (Main.JobEventReceived anonymousBadEvent) fresh
                        |> Expect.equal fresh
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


{-| An unreadable frame, produced the way the subscription produces one:
by running `Main.readEvent` — the real function the port is wired to — over the
wrong shape. It used to build a bare `Decode.Error`, which could not say which
stream the frame came from; that is now the whole point of the type, so the
fixture goes through the real reader rather than around it.

`id` is `j1`, the job the `watching` model is watching, so this frame is the
separation's.
-}
badEvent : Result Main.BadEvent Api.Job
badEvent =
    Main.readEvent (Json.Encode.object [ ( "id", Json.Encode.string "j1" ) ])


{-| The same, from the stream a render is being watched on.
-}
badRenderEvent : Result Main.BadEvent Api.Job
badRenderEvent =
    Main.readEvent (Json.Encode.object [ ( "id", Json.Encode.string "render-job" ) ])


{-| And one that does not say where it came from at all.
-}
anonymousBadEvent : Result Main.BadEvent Api.Job
anonymousBadEvent =
    Main.readEvent (Json.Encode.object [ ( "fraction", Json.Encode.float 0.5 ) ])
