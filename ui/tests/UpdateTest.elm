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
import Http
import Json.Encode
import Main
import Page.Queue as Queue
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
                            , lastPresetId = Nothing
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
        , describe "cancelling a job from the queue"
            -- Nothing tested this end of the round trip at all. `grep -rn
            -- "Cancellation\|CancelSent" ui/tests/` came back empty, and the
            -- Python side asserts `answer["cancelled"] is True` off a
            -- hand-read dict — so the seam between the two halves was
            -- unwatched from both sides, which is the shape this project has
            -- already been bitten by twice.
            --
            -- Mutation-proved: inverting the `if answer.cancelled` branch left
            -- all 311 Elm and 268 Python tests green while every successful
            -- cancel told the operator "That job had already finished, so
            -- nothing was stopped" and skipped the re-fetch, leaving the row
            -- with its Cancel button intact.
            [ test "a cancel that stopped something says nothing and leaves no complaint" <|
                \_ ->
                    -- Starting from a model that already has a complaint, so
                    -- this cannot pass merely because nothing was written.
                    let
                        ( fresh, _ ) =
                            Main.init ()

                        stale =
                            { fresh | queueProblem = Just "something older" }
                    in
                    stale
                        |> step (Main.JobCancelSent (Ok (cancellationOf True Api.Running)))
                        |> .queueProblem
                        |> Expect.equal Nothing
            , test "a cancel that was refused says so" <|
                \_ ->
                    let
                        ( fresh, _ ) =
                            Main.init ()
                    in
                    fresh
                        |> step (Main.JobCancelSent (Ok (cancellationOf False Api.Cancelled)))
                        |> .queueProblem
                        |> Expect.notEqual Nothing
            , test "a stopped job that still reads running is not reported as a refusal" <|
                \_ ->
                    -- The whole reason `cancelled` exists as a field of its
                    -- own. The route cancels and then re-reads, so a genuinely
                    -- stopped job comes back at whatever status it held that
                    -- instant — `running` for a separation whose worker has
                    -- not noticed yet, and `done` for one that finished in the
                    -- window. Reading the status instead would tell the
                    -- operator nothing was stopped about a cancel that worked.
                    let
                        ( fresh, _ ) =
                            Main.init ()

                        answered status =
                            fresh
                                |> step (Main.JobCancelSent (Ok (cancellationOf True status)))
                                |> .queueProblem
                    in
                    Expect.all
                        [ \_ -> Expect.equal Nothing (answered Api.Running)
                        , \_ -> Expect.equal Nothing (answered Api.Done)
                        ]
                        ()
            , test "clicking Cancel clears whatever the last one said" <|
                \_ ->
                    let
                        ( fresh, _ ) =
                            Main.init ()
                    in
                    { fresh | queueProblem = Just "the last cancel was refused" }
                        |> step (Main.CancelJobClicked "j1")
                        |> .queueProblem
                        |> Expect.equal Nothing
            , test "a failed cancel request says something too" <|
                \_ ->
                    let
                        ( fresh, _ ) =
                            Main.init ()
                    in
                    fresh
                        |> step (Main.JobCancelSent (Err (Http.BadStatus 500)))
                        |> .queueProblem
                        |> Expect.notEqual Nothing
            ]
        , describe "the queue screen's poll"
            -- What these can and cannot see, stated up front. `Cmd` has no
            -- equality in Elm, so none of this observes a request going out or
            -- a timer being armed. What it does hold is the invariant the
            -- chain's correctness rests on — exactly one chain while the screen
            -- is open, none while it is closed — which lives today in a
            -- convention nothing enforces: only `OpenQueue` writes `queueTick`.
            -- A `queue = Just …` written anywhere else would break it silently,
            -- and these are what would notice.
            [ test "opening the queue takes a chain id that the initial model could never be mistaken for" <|
                \_ ->
                    -- `queueTick` starts at 0 and `nextRequest` at 1, so the
                    -- id every chain is issued is non-zero. That is what stops
                    -- a `QueueTick 0` — the only tick value reachable without
                    -- anyone having opened the screen — from being honoured.
                    let
                        ( fresh, _ ) =
                            Main.init ()

                        opened =
                            step Main.OpenQueue fresh
                    in
                    Expect.all
                        [ \_ -> Expect.equal 0 fresh.queueTick
                        , \_ -> Expect.notEqual 0 opened.queueTick
                        , \_ -> Expect.equal (Just Queue.Loading) opened.queue
                        ]
                        ()
            , test "reopening the queue issues a fresh chain id rather than reusing the last one" <|
                \_ ->
                    -- The case this exists for is a double-click, or leaving
                    -- and coming back inside the poll interval: the first
                    -- chain's sleep is still in flight when the second starts.
                    -- Two chains on one screen would double the request rate
                    -- for the rest of the session, and only the id tells them
                    -- apart.
                    let
                        ( fresh, _ ) =
                            Main.init ()

                        first =
                            step Main.OpenQueue fresh

                        second =
                            first
                                |> step Main.CloseQueue
                                |> step Main.OpenQueue
                    in
                    Expect.notEqual first.queueTick second.queueTick
            , test "a tick from a superseded chain leaves the model exactly as it was" <|
                \_ ->
                    -- Weaker than it looks, and worth being honest about: the
                    -- live branch also returns the model unchanged, so this
                    -- cannot see the difference between polling and not. What
                    -- it does catch is `QueueTick` growing a model write —
                    -- after which a stale tick would start editing a screen it
                    -- no longer belongs to.
                    let
                        ( fresh, _ ) =
                            Main.init ()

                        first =
                            step Main.OpenQueue fresh

                        reopened =
                            first
                                |> step Main.CloseQueue
                                |> step Main.OpenQueue
                                |> step (Main.GotQueueJobs (Ok [ queuedJob ]))

                        afterStaleTick =
                            step (Main.QueueTick first.queueTick) reopened
                    in
                    Expect.all
                        [ \_ -> Expect.equal reopened.queue afterStaleTick.queue
                        , \_ -> Expect.equal reopened.queueTick afterStaleTick.queueTick
                        , \_ -> Expect.equal reopened.queueProblem afterStaleTick.queueProblem
                        ]
                        ()
            , test "a tick that lands after the screen closed does not reopen it" <|
                \_ ->
                    let
                        ( fresh, _ ) =
                            Main.init ()

                        opened =
                            step Main.OpenQueue fresh
                    in
                    opened
                        |> step Main.CloseQueue
                        |> step (Main.QueueTick opened.queueTick)
                        |> .queue
                        |> Expect.equal Nothing
            , test "a poll that lands after the screen closed does not reopen it either" <|
                \_ ->
                    -- `queue` is what `routeFor` reads to decide which screen
                    -- is showing, so writing a late response back would put the
                    -- queue over whatever the user moved on to.
                    let
                        ( fresh, _ ) =
                            Main.init ()
                    in
                    fresh
                        |> step Main.OpenQueue
                        |> step Main.CloseQueue
                        |> step (Main.GotQueueJobs (Ok [ queuedJob ]))
                        |> .queue
                        |> Expect.equal Nothing
            , test "a successful poll clears the note left by a cancel that came too late" <|
                \_ ->
                    -- The note explains why a row did not do what the button
                    -- implied; these are the rows that show what actually
                    -- happened, so the note has nothing left to explain.
                    let
                        ( fresh, _ ) =
                            Main.init ()

                        complaining =
                            { fresh
                                | queue = Just Queue.Loading
                                , queueProblem = Just "That job had already finished"
                            }
                    in
                    complaining
                        |> step (Main.GotQueueJobs (Ok [ queuedJob ]))
                        |> .queueProblem
                        |> Expect.equal Nothing
            , test "the queue and the renders screen are never open at once" <|
                \_ ->
                    -- Which is what makes `routeFor`'s order between the two
                    -- not load-bearing.
                    let
                        ( fresh, _ ) =
                            Main.init ()

                        queueOverRenders =
                            fresh |> step Main.OpenRenders |> step Main.OpenQueue

                        rendersOverQueue =
                            fresh |> step Main.OpenQueue |> step Main.OpenRenders
                    in
                    Expect.all
                        [ \_ -> Expect.equal Nothing queueOverRenders.renders
                        , \_ -> Expect.notEqual Nothing queueOverRenders.queue
                        , \_ -> Expect.equal Nothing rendersOverQueue.queue
                        , \_ -> Expect.notEqual Nothing rendersOverQueue.renders
                        ]
                        ()
            ]
        ]


{-| What `POST /api/jobs/{id}/cancel` answers, in the two parts that disagree.

`cancelled` and the job's status are supplied separately on purpose: they are
independent on the wire, and treating them as one is the mistake these tests
exist to catch. `ApiTest` holds the captured JSON that proves this shape is the
server's; this is the value that shape decodes to.
-}
cancellationOf : Bool -> Api.JobStatus -> Api.Cancellation
cancellationOf cancelled status =
    { cancelled = cancelled
    , job = aJob "j1" status 0.0
    }


{-| A job as `GET /api/jobs` would list one that has not started yet.
-}
queuedJob : Api.Job
queuedJob =
    { id = "queued-1"
    , kind = "render"
    , status = Api.Queued
    , fraction = 0.0
    , message = ""
    , songId = Just "song-1"
    , renderId = Just "r1"
    , createdAt = "2026-08-04T21:04:00.000000+00:00"
    }


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
