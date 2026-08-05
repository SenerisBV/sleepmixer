module QueueTest exposing (suite)

{-| The decisions on the queue screen, which are all ordering and grouping.

The screen exists because one worker runs everything, so a long job blocks
every job behind it — the operator hit this by importing a seventy-minute file
by accident and having to kill the server by hand to get out of it. What that
makes worth testing is the part that says *what is in the way*: which rows come
first, in which order inside each group, which of them can still be stopped, and
what the screen says when there are no rows at all.

The view itself is markup and `elm-test` does not look at it; the classes it
emits are checked from the Python side by
`tests/test_static_bundle.py::test_every_class_the_views_emit_has_a_rule_on_the_page`.

**Every ordering test supplies more than one input order.** `GET /api/jobs`
answers in submission order already, so a test given one arrangement passes
against a sort that does nothing at all — which is the sort the real screen
would then have, with this file green.

-}

import Api
import Expect
import Page.Queue as Queue
import Test exposing (Test, describe, test)


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


{-| A job to adjust per test by record update. `renderId` is `Just` on renders
and `Nothing` on separations, which is what the decoder guarantees.
-}
aJob : String -> String -> Api.Job
aJob id createdAt =
    { id = id
    , kind = "render"
    , status = Api.Queued
    , fraction = 0.0
    , message = ""
    , songId = Just "s1"
    , renderId = Just ("r-" ++ id)
    , createdAt = createdAt
    }


{-| Three instants, an hour apart, in the shape the server writes them.
-}
nine : String
nine =
    "2026-08-04T09:00:00.100000+00:00"


ten : String
ten =
    "2026-08-04T10:00:00.100000+00:00"


eleven : String
eleven =
    "2026-08-04T11:00:00.100000+00:00"


ids : List Api.Job -> List String
ids =
    List.map .id


suite : Test
suite =
    describe "Page.Queue"
        [ describe "what is in the way, and in what order"
            [ test "the job that is running is listed above one that is only waiting, even though it was submitted later" <|
                \_ ->
                    -- The running job is the *newer* of the two on purpose: a
                    -- plain `created_at` sort would put it second, so this
                    -- cannot pass unless running genuinely outranks queued.
                    let
                        waiting =
                            { queued | id = "waiting", createdAt = nine }

                        queued =
                            aJob "running" eleven

                        running =
                            { queued | status = Api.Running }
                    in
                    Expect.all
                        [ \_ -> Expect.equal [ "running", "waiting" ] (ids (Queue.ordered [ waiting, running ]))
                        , \_ -> Expect.equal [ "running", "waiting" ] (ids (Queue.ordered [ running, waiting ]))
                        ]
                        ()
            , test "jobs that are waiting are listed in the order they were submitted, not the order the response happened to arrive in" <|
                \_ ->
                    let
                        first =
                            aJob "first" nine

                        second =
                            aJob "second" ten

                        third =
                            aJob "third" eleven

                        expected =
                            [ "first", "second", "third" ]
                    in
                    Expect.all
                        [ \_ -> Expect.equal expected (ids (Queue.ordered [ third, first, second ]))
                        , \_ -> Expect.equal expected (ids (Queue.ordered [ second, third, first ]))
                        , \_ -> Expect.equal expected (ids (Queue.ordered [ first, second, third ]))
                        ]
                        ()
            , test "a job that has already ended is listed below one that is still waiting, however long ago it ended" <|
                \_ ->
                    -- The finished job is the oldest of the three, so a sort
                    -- that only reads `created_at` would put it at the top —
                    -- pushing the thing actually blocking the worker off the
                    -- first screenful, which is the one thing this page is for.
                    let
                        finished =
                            { waiting | id = "finished", status = Api.Done, createdAt = nine }

                        waiting =
                            aJob "waiting" ten

                        running =
                            { waiting | id = "running", status = Api.Running, createdAt = eleven }

                        expected =
                            [ "running", "waiting", "finished" ]
                    in
                    Expect.all
                        [ \_ -> Expect.equal expected (ids (Queue.ordered [ finished, waiting, running ]))
                        , \_ -> Expect.equal expected (ids (Queue.ordered [ running, finished, waiting ]))
                        , \_ -> Expect.equal expected (ids (Queue.ordered [ waiting, running, finished ]))
                        ]
                        ()
            , test "among the jobs that have ended the most recent is first, not last" <|
                \_ ->
                    -- The opposite direction from the two live groups, on
                    -- purpose. The manager keeps fifty terminal jobs and this
                    -- screen has no pagination, so oldest-first would put the
                    -- render that failed a minute ago — the row you opened the
                    -- screen to read — at the bottom of forty-nine you did not.
                    let
                        oldest =
                            { sample | id = "oldest", status = Api.Done, createdAt = nine }

                        middle =
                            { oldest | id = "middle", status = Api.Cancelled, createdAt = ten }

                        newest =
                            { oldest | id = "newest", status = Api.Failed "boom", createdAt = eleven }

                        expected =
                            [ "newest", "middle", "oldest" ]
                    in
                    Expect.all
                        [ \_ -> Expect.equal expected (ids (Queue.ordered [ oldest, middle, newest ]))
                        , \_ -> Expect.equal expected (ids (Queue.ordered [ middle, newest, oldest ]))
                        , \_ -> Expect.equal expected (ids (Queue.ordered [ newest, oldest, middle ]))
                        ]
                        ()
            , test "the live groups still read forward in time while the ended one reads backward" <|
                \_ ->
                    -- Both directions in one list, because they are two rules
                    -- and a single `sortBy` cannot express them: a sort that
                    -- reversed everything would fail on the two waiting jobs,
                    -- and one that reversed nothing would fail on the two that
                    -- ended.
                    let
                        base =
                            aJob "x" ten

                        running =
                            { base | id = "running", status = Api.Running, createdAt = eleven }

                        waitingOld =
                            { base | id = "waiting-old", status = Api.Queued, createdAt = nine }

                        waitingNew =
                            { base | id = "waiting-new", status = Api.Queued, createdAt = eleven }

                        endedOld =
                            { base | id = "ended-old", status = Api.Done, createdAt = nine }

                        endedNew =
                            { base | id = "ended-new", status = Api.Done, createdAt = eleven }
                    in
                    Queue.ordered [ endedOld, waitingNew, running, endedNew, waitingOld ]
                        |> ids
                        |> Expect.equal
                            [ "running", "waiting-old", "waiting-new", "ended-new", "ended-old" ]
            , test "separations and renders queue together, because they share the one worker" <|
                \_ ->
                    -- The screen would be a lie if it split them: a separation
                    -- ahead of a render is what the render is waiting for.
                    let
                        separation =
                            { render | id = "separation", kind = "separate", renderId = Nothing, createdAt = nine }

                        render =
                            aJob "render" ten
                    in
                    Expect.equal [ "separation", "render" ]
                        (ids (Queue.ordered [ render, separation ]))
            ]
        , describe "what can still be stopped"
            [ test "a job that has finished offers nothing to cancel" <|
                \_ ->
                    let
                        ended status =
                            Queue.cancellable { sample | status = status }
                    in
                    Expect.equal [ False, False, False ]
                        [ ended Api.Done
                        , ended Api.Cancelled
                        , ended (Api.Failed "LibsndfileError: Permission denied")
                        ]
            , test "a job that is running or waiting can be cancelled, which is the point of the screen" <|
                \_ ->
                    Expect.equal [ True, True ]
                        [ Queue.cancellable { sample | status = Api.Running }
                        , Queue.cancellable { sample | status = Api.Queued }
                        ]
            ]
        , describe "an empty queue"
            [ test "an empty list explains itself rather than showing nothing" <|
                \_ ->
                    -- A blank screen for a structural reason — the manager
                    -- holds its jobs in memory and starts over on every server
                    -- start — is the same class of problem as a progress bar
                    -- with no bar.
                    case Queue.emptyNote [] of
                        Nothing ->
                            Expect.fail "an empty queue said nothing at all"

                        Just words ->
                            Expect.equal True (String.contains "restart" words)
            , test "a queue with something in it says nothing in place of the rows" <|
                \_ ->
                    Queue.emptyNote [ sample ] |> Expect.equal Nothing
            ]
        , describe "what a row says about itself"
            [ test "a job is listed under the title of the song it belongs to" <|
                \_ ->
                    Queue.subject [ aSong "s2" "Other", aSong "s1" "Nocturne" ] sample
                        |> Expect.equal "Nocturne"
            , test "a job whose song has been removed shows the id rather than an empty cell" <|
                \_ ->
                    Queue.subject [ aSong "s2" "Other" ] sample
                        |> Expect.equal "s1"
            , test "a job carrying no song at all says so rather than reading as an untitled one" <|
                \_ ->
                    Queue.subject [ aSong "s1" "Nocturne" ] { sample | songId = Nothing }
                        |> Expect.equal "no song recorded"
            , test "a separation is named as a separation and a render as a render" <|
                \_ ->
                    Expect.equal [ "separation", "render" ]
                        [ Queue.kindLabel "separate", Queue.kindLabel "render" ]
            , test "a kind this build does not know is shown as the server said it, not renamed" <|
                \_ ->
                    Queue.kindLabel "transcode" |> Expect.equal "transcode"
            , test "a job that is waiting says what it is waiting for" <|
                \_ ->
                    Queue.detailFor { sample | status = Api.Queued, message = "" }
                        |> String.contains "one job runs at a time"
                        |> Expect.equal True
            , test "a failed job carries the reason it recorded rather than the bare word" <|
                \_ ->
                    Queue.detailFor
                        { sample | status = Api.Failed "LibsndfileError: Permission denied" }
                        |> Expect.equal "LibsndfileError: Permission denied"
            ]
        , describe "a poll that did not come back"
            [ test "a failed refresh keeps the rows it already had rather than blanking them" <|
                \_ ->
                    -- The screen polls every few seconds, so one dropped
                    -- request must not replace a list of live jobs with an
                    -- error. The rows go stale; they do not go away.
                    Queue.afterFailedPoll "could not reach the server" (Queue.Loaded [ sample ])
                        |> Expect.equal (Queue.Stale [ sample ] "could not reach the server")
            , test "rows kept after a failed refresh are not left looking current" <|
                \_ ->
                    -- A Cancel button drawn from a snapshot of unknown age is a
                    -- button that might stop something other than what it is
                    -- next to, so the reason travels with the rows.
                    Queue.staleNote "could not reach the server"
                        |> String.contains "could not reach the server"
                        |> Expect.equal True
            , test "a second failed refresh keeps the same rows and takes the newer reason" <|
                \_ ->
                    Queue.afterFailedPoll "the server answered 500"
                        (Queue.Stale [ sample ] "could not reach the server")
                        |> Expect.equal (Queue.Stale [ sample ] "the server answered 500")
            , test "a first fetch that failed has no rows to keep and says why" <|
                \_ ->
                    Queue.afterFailedPoll "could not reach the server" Queue.Loading
                        |> Expect.equal (Queue.Failed "could not reach the server")
            ]
        ]


sample : Api.Job
sample =
    aJob "j1" ten
