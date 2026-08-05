module ApiTest exposing (suite)

import Api
import Expect
import Json.Decode as Decode
import Test exposing (Test, describe, test)


songJson : String
songJson =
    """
    { "id": "abc", "path": "/music/a.flac", "title": "A"
    , "duration_s": 214.5, "sample_rate": 44100
    , "separation_status": "done", "separation_reason": null
    , "stems": ["bass", "drums", "other", "vocals"]
    , "added_at": "2026-08-04T10:00:00+00:00" }
    """


{- The five render fixtures below are captured verbatim from a live
`GET`/`POST /api/renders` against a throwaway data dir
(`SLEEPMIX_DATA_DIR=$(mktemp -d) pipenv run sleepmix ui --no-open --port 8765`).
The only edit made to any of them is replacing the real, machine-specific
`/var/folders/.../renders/...` path with `/tmp/data/renders/...` — a
deliberate normalisation of an irrelevant field, not a rewrite of anything the
decoder is tested against. Every other field, including `id`, `config` and
`created_at`, is the byte-for-byte value the server actually returned.
-}


{-| Captured from the `POST /api/renders` response body itself — the row it
creates up front, before the worker thread has picked the job up. `config`
comes back as a real JSON object (not a string of JSON: `store._render_from_row`
does `json.loads` before the row ever reaches the route), and `duration_min`
is `null` before the render finishes.
-}
queuedRenderJson : String
queuedRenderJson =
    """
    { "id": "f591fb3734714c8f9916e7ed891b978f"
    , "song_id": "15ff79b16efd4fc58874df4eac097a38"
    , "config": {"output": {"duration_min": 0.05, "sample_rate": 22050,
                            "fade_in_s": 0.0, "fade_out_s": 0.0}}
    , "path": "/tmp/data/renders/f591fb3734714c8f9916e7ed891b978f.wav"
    , "status": "queued", "duration_min": null
    , "created_at": "2026-08-04T21:03:35.473657+00:00" }
    """


{-| Same live capture, polled again once the worker picked the job up.
-}
runningRenderJson : String
runningRenderJson =
    """
    { "id": "aadbfb45ff2b45e380abb4f78d14c393"
    , "song_id": "15ff79b16efd4fc58874df4eac097a38"
    , "config": {}
    , "path": "/tmp/data/renders/aadbfb45ff2b45e380abb4f78d14c393.wav"
    , "status": "running", "duration_min": null
    , "created_at": "2026-08-04T21:03:17.582197+00:00" }
    """


{-| A real render that ran to completion, using the same tiny `output.config`
(`duration_min: 0.05`, `sample_rate: 22050`) the Python test suite's
`_a_finished_render` helper uses, so it finished in well under a second rather
than the minutes a real 20+-minute mix would take. `config` here is nested,
confirming it round-trips as a real object rather than a flattened one.
-}
doneRenderJson : String
doneRenderJson =
    """
    { "id": "f591fb3734714c8f9916e7ed891b978f"
    , "song_id": "15ff79b16efd4fc58874df4eac097a38"
    , "config": {"output": {"duration_min": 0.05, "sample_rate": 22050,
                            "fade_in_s": 0.0, "fade_out_s": 0.0}}
    , "path": "/tmp/data/renders/f591fb3734714c8f9916e7ed891b978f.wav"
    , "status": "done", "duration_min": 0.05
    , "created_at": "2026-08-04T21:03:35.473657+00:00" }
    """


{-| Cancelled by `POST /api/jobs/{id}/cancel` while genuinely running (started
with no config override, so it was mid-render — real separation, not a stub).
`duration_min` stays `null`: a cancelled render never reaches the point that
sets it.
-}
cancelledRenderJson : String
cancelledRenderJson =
    """
    { "id": "aadbfb45ff2b45e380abb4f78d14c393"
    , "song_id": "15ff79b16efd4fc58874df4eac097a38"
    , "config": {}
    , "path": "/tmp/data/renders/aadbfb45ff2b45e380abb4f78d14c393.wav"
    , "status": "cancelled", "duration_min": null
    , "created_at": "2026-08-04T21:03:17.582197+00:00" }
    """


{-| Made to fail for real: the renders directory was `chmod 555`'d before this
one was started, so `save_audio` hit a genuine `LibsndfileError` writing the
output file and the job manager recorded the row as `failed`. `duration_min`
stays `null` here too.
-}
failedRenderJson : String
failedRenderJson =
    """
    { "id": "d45d41a033dc4fa29a3ffa4fe2930f1e"
    , "song_id": "15ff79b16efd4fc58874df4eac097a38"
    , "config": {"output": {"duration_min": 0.05, "sample_rate": 22050,
                            "fade_in_s": 0.0, "fade_out_s": 0.0}}
    , "path": "/tmp/data/renders/d45d41a033dc4fa29a3ffa4fe2930f1e.wav"
    , "status": "failed", "duration_min": null
    , "created_at": "2026-08-04T21:03:57.643702+00:00" }
    """


{- The two cancellation fixtures below are captured from real
`POST /api/jobs/{id}/cancel` responses against a throwaway `SLEEPMIX_DATA_DIR`,
byte for byte, with only the JSON re-indented to fit here. The separation they
cancel ran `tests/stub_separation_worker` rather than Demucs — the worker is
the one part of that request that is a stand-in, and it is downstream of every
line this decoder reads. The route, the job manager and `Job.as_event` are all
the real ones.

Two responses because there are two, behind one 200, and `cancelled` is the
only thing that tells them apart: a running job genuinely stopped, and a job
that had already ended before the request arrived.
-}


cancelledJobJson : String
cancelledJobJson =
    """
    { "cancelled": true
    , "job":
        { "id": "68ec100df7914346a10bf262f4f8073d"
        , "kind": "separate", "status": "running"
        , "fraction": 0.0, "message": "Separating stems\\u2026"
        , "error": null, "result": null
        , "song_id": "f2d624a566e344adb4490239b2e4855f"
        , "render_id": null
        , "created_at": "2026-08-05T00:35:22.500717+00:00" }
    }
    """


refusedCancelJson : String
refusedCancelJson =
    """
    { "cancelled": false
    , "job":
        { "id": "68ec100df7914346a10bf262f4f8073d"
        , "kind": "separate", "status": "cancelled"
        , "fraction": 0.0, "message": "Cancelled"
        , "error": null, "result": null
        , "song_id": "f2d624a566e344adb4490239b2e4855f"
        , "render_id": null
        , "created_at": "2026-08-05T00:35:22.500717+00:00" }
    }
    """


suite : Test
suite =
    describe "Api"
        [ describe "song"
            [ test "decodes a separated song" <|
                \_ ->
                    case Decode.decodeString Api.song songJson of
                        Ok s ->
                            Expect.all
                                [ .id >> Expect.equal "abc"
                                , .title >> Expect.equal "A"
                                , .durationS >> Expect.within (Expect.Absolute 0.01) 214.5
                                , .stems >> Expect.equal [ "bass", "drums", "other", "vocals" ]
                                , .separationStatus >> Expect.equal Api.Separated
                                ]
                                s

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            , test "decodes a song that has not been separated" <|
                \_ ->
                    let
                        json =
                            """
                            { "id": "x", "path": "/m/b.wav", "title": "B"
                            , "duration_s": 10.0, "sample_rate": 44100
                            , "separation_status": "pending", "separation_reason": null
                            , "stems": null
                            , "added_at": "2026-08-04T10:00:00+00:00" }
                            """
                    in
                    case Decode.decodeString Api.song json of
                        Ok s ->
                            Expect.all
                                [ .separationStatus >> Expect.equal Api.NotSeparated
                                , .stems >> Expect.equal []
                                ]
                                s

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            , test "keeps the reason when separation fell back" <|
                \_ ->
                    let
                        json =
                            """
                            { "id": "x", "path": "/m/b.wav", "title": "B"
                            , "duration_s": 10.0, "sample_rate": 44100
                            , "separation_status": "fallback"
                            , "separation_reason": "Demucs unavailable (no torch)"
                            , "stems": ["mix"]
                            , "added_at": "2026-08-04T10:00:00+00:00" }
                            """
                    in
                    case Decode.decodeString Api.song json of
                        Ok s ->
                            Expect.equal
                                (Api.Fallback "Demucs unavailable (no torch)")
                                s.separationStatus

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            , test "an unknown status fails loudly rather than being ignored" <|
                \_ ->
                    let
                        json =
                            """
                            { "id": "x", "path": "/m/b.wav", "title": "B"
                            , "duration_s": 10.0, "sample_rate": 44100
                            , "separation_status": "teleporting", "separation_reason": null
                            , "stems": null
                            , "added_at": "2026-08-04T10:00:00+00:00" }
                            """
                    in
                    Decode.decodeString Api.song json
                        |> Expect.err
            ]
        , describe "job"
            [ test "decodes a running job" <|
                \_ ->
                    let
                        json =
                            """
                            { "id": "j1", "kind": "separate", "status": "running"
                            , "fraction": 0.42, "message": "Separating stems…"
                            , "error": null, "result": null, "song_id": "abc"
                            , "render_id": null
                            , "created_at": "2026-08-04T21:03:17.584296+00:00" }
                            """
                    in
                    case Decode.decodeString Api.job json of
                        Ok j ->
                            Expect.all
                                [ .status >> Expect.equal Api.Running
                                , .fraction >> Expect.within (Expect.Absolute 0.001) 0.42
                                , .message >> Expect.equal "Separating stems…"
                                ]
                                j

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            , test "carries the error text on a failed job" <|
                \_ ->
                    let
                        json =
                            """
                            { "id": "j1", "kind": "render", "status": "failed"
                            , "fraction": 0.3, "message": "Failed"
                            , "error": "RuntimeError: disk full"
                            , "result": null, "song_id": "abc", "render_id": "r1"
                            , "created_at": "2026-08-04T21:03:57.645410+00:00" }
                            """
                    in
                    case Decode.decodeString Api.job json of
                        Ok j ->
                            Expect.equal (Api.Failed "RuntimeError: disk full") j.status

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            , test "carries created_at and the id of the render it is producing, captured from a live POST /api/renders envelope's job field" <|
                \_ ->
                    -- Re-captured verbatim after the job dataclass grew
                    -- `render_id`, rather than hand-edited: an earlier fixture
                    -- on this branch was patched to look captured, and a
                    -- fixture that *looks* captured is worse than an obviously
                    -- written one because the next reader takes it as evidence.
                    -- `render_id` here is the same hex the same response's
                    -- `render.id` carried, which is the pairing the renders
                    -- screen depends on.
                    let
                        json =
                            """
                            { "id": "a0e4cf2918d140119ad26d5e31006c06", "kind": "render"
                            , "status": "running", "fraction": 0.0, "message": ""
                            , "error": null, "result": null
                            , "song_id": "ec08ea8c6f4449ab81e0711211761653"
                            , "render_id": "0f4cf8f62db248d7be05aa54c25dfed0"
                            , "created_at": "2026-08-04T21:51:07.563535+00:00" }
                            """
                    in
                    case Decode.decodeString Api.job json of
                        Ok j ->
                            Expect.all
                                [ .createdAt >> Expect.equal "2026-08-04T21:51:07.563535+00:00"
                                , .renderId >> Expect.equal (Just "0f4cf8f62db248d7be05aa54c25dfed0")
                                ]
                                j

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            , test "a separation's job carries no render id, captured live from POST /api/songs/{id}/separate" <|
                \_ ->
                    -- Null rather than absent, and that distinction is the
                    -- decoder's: `render_id` is required-and-nullable like
                    -- `song_id`, so a server that stopped sending the field
                    -- fails loudly instead of decoding to the `Nothing` that
                    -- means "this render has no job".
                    let
                        json =
                            """
                            { "id": "e3a021c0975348e8819694494c935527", "kind": "separate"
                            , "status": "queued", "fraction": 0.0, "message": ""
                            , "error": null, "result": null
                            , "song_id": "ec08ea8c6f4449ab81e0711211761653"
                            , "render_id": null
                            , "created_at": "2026-08-04T21:51:07.567838+00:00" }
                            """
                    in
                    case Decode.decodeString Api.job json of
                        Ok j ->
                            Expect.equal Nothing j.renderId

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            , test "a job missing render_id fails the decode rather than defaulting to none" <|
                \_ ->
                    let
                        json =
                            """
                            { "id": "j1", "kind": "render", "status": "running"
                            , "fraction": 0.0, "message": "", "error": null
                            , "result": null, "song_id": "abc"
                            , "created_at": "2026-08-04T21:03:17.584296+00:00" }
                            """
                    in
                    Decode.decodeString Api.job json
                        |> Expect.err
            , test "a job missing created_at fails the decode rather than defaulting" <|
                \_ ->
                    let
                        json =
                            """
                            { "id": "j1", "kind": "render", "status": "running"
                            , "fraction": 0.0, "message": "", "error": null
                            , "result": null, "song_id": "abc" }
                            """
                    in
                    Decode.decodeString Api.job json
                        |> Expect.err
            , test "isFinished is true only for terminal statuses" <|
                \_ ->
                    Expect.equal
                        [ False, False, True, True, True ]
                        (List.map Api.isFinished
                            [ Api.Queued
                            , Api.Running
                            , Api.Done
                            , Api.Cancelled
                            , Api.Failed "x"
                            ]
                        )
            ]
        , describe "render"
            [ test "decodes a queued render with duration_min null" <|
                \_ ->
                    case Decode.decodeString Api.render queuedRenderJson of
                        Ok r ->
                            Expect.all
                                [ .status >> Expect.equal Api.RenderQueued
                                , .durationMin >> Expect.equal Nothing
                                , .songId >> Expect.equal "15ff79b16efd4fc58874df4eac097a38"
                                ]
                                r

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            , test "decodes a running render" <|
                \_ ->
                    case Decode.decodeString Api.render runningRenderJson of
                        Ok r ->
                            Expect.all
                                [ .status >> Expect.equal Api.RenderRunning
                                , .durationMin >> Expect.equal Nothing
                                ]
                                r

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            , test "decodes a done render with a Just duration, and config as a real object" <|
                \_ ->
                    case Decode.decodeString Api.render doneRenderJson of
                        Ok r ->
                            Expect.all
                                [ .status >> Expect.equal Api.RenderDone
                                , .durationMin >> Expect.equal (Just 0.05)
                                , .config
                                    >> Decode.decodeValue
                                        (Decode.at [ "output", "duration_min" ] Decode.float)
                                    >> Expect.equal (Ok 0.05)
                                ]
                                r

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            , test "decodes a cancelled render" <|
                \_ ->
                    case Decode.decodeString Api.render cancelledRenderJson of
                        Ok r ->
                            Expect.all
                                [ .status >> Expect.equal Api.RenderCancelled
                                , .durationMin >> Expect.equal Nothing
                                ]
                                r

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            , test "decodes a failed render" <|
                \_ ->
                    case Decode.decodeString Api.render failedRenderJson of
                        Ok r ->
                            Expect.all
                                [ .status >> Expect.equal Api.RenderFailed
                                , .durationMin >> Expect.equal Nothing
                                ]
                                r

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            , test "an unknown render status fails loudly rather than being ignored" <|
                \_ ->
                    let
                        json =
                            """
                            { "id": "x", "song_id": "abc", "config": {}
                            , "path": "/tmp/x.wav", "status": "teleporting"
                            , "duration_min": null
                            , "created_at": "2026-08-04T10:00:00+00:00" }
                            """
                    in
                    Decode.decodeString Api.render json
                        |> Expect.err
            , test "isRenderFinished is true only for terminal statuses" <|
                \_ ->
                    Expect.equal
                        [ False, False, True, True, True ]
                        (List.map Api.isRenderFinished
                            [ Api.RenderQueued
                            , Api.RenderRunning
                            , Api.RenderDone
                            , Api.RenderFailed
                            , Api.RenderCancelled
                            ]
                        )
            ]
        , describe "cancellation"
            [ test "a cancel that stopped something decodes as cancelled" <|
                \_ ->
                    case Decode.decodeString Api.cancellation cancelledJobJson of
                        Ok answer ->
                            Expect.all
                                [ .cancelled >> Expect.equal True
                                , .job >> .id >> Expect.equal "68ec100df7914346a10bf262f4f8073d"
                                , .job >> .status >> Expect.equal Api.Running
                                ]
                                answer

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            , test "the job's status is not the answer — a stopped job still reads running" <|
                \_ ->
                    -- The route cancels and then re-reads, so a job that was
                    -- genuinely stopped comes back at whatever status it held
                    -- at that instant. Deriving "was it refused?" from the
                    -- status would report "nothing was stopped" about a cancel
                    -- that worked, so the two fields have to be decoded, and
                    -- read, separately.
                    Decode.decodeString Api.cancellation cancelledJobJson
                        |> Result.map (\a -> ( a.cancelled, a.job.status ))
                        |> Expect.equal (Ok ( True, Api.Running ))
            , test "a cancel that was refused decodes as not cancelled" <|
                \_ ->
                    Decode.decodeString Api.cancellation refusedCancelJson
                        |> Result.map .cancelled
                        |> Expect.equal (Ok False)
            , test "a response missing `cancelled` fails rather than defaulting" <|
                \_ ->
                    -- Defaulting either way is a lie in one direction: to False
                    -- it claims a working cancel did nothing, to True it stays
                    -- silent about a Cancel button that did nothing.
                    let
                        json =
                            String.replace "\"cancelled\": true" "\"ignored\": true"
                                cancelledJobJson
                    in
                    Decode.decodeString Api.cancellation json
                        |> Expect.err
            ]
        ]
