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


{-| Captured from a live `GET /api/renders` against a throwaway data dir
(`SLEEPMIX_DATA_DIR=$(mktemp -d) pipenv run sleepmix ui --no-open --port 8765`),
right after `POST /api/renders` answered — before the worker thread has picked
the job up. `config` comes back as a real JSON object (not a string of JSON:
`store._render_from_row` does `json.loads` before the row ever reaches the
route), and `duration_min` is `null` before the render finishes.
-}
queuedRenderJson : String
queuedRenderJson =
    """
    { "id": "d45d41a033dc4fa29a3ffa4fe2930f1e"
    , "song_id": "15ff79b16efd4fc58874df4eac097a38"
    , "config": {}
    , "path": "/tmp/data/renders/d45d41a033dc4fa29a3ffa4fe2930f1e.wav"
    , "status": "queued", "duration_min": null
    , "created_at": "2026-08-04T21:03:57.643702+00:00" }
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
                            , "result": null, "song_id": "abc"
                            , "created_at": "2026-08-04T21:03:57.645410+00:00" }
                            """
                    in
                    case Decode.decodeString Api.job json of
                        Ok j ->
                            Expect.equal (Api.Failed "RuntimeError: disk full") j.status

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            , test "carries created_at, captured from a live POST /api/renders envelope's job field" <|
                \_ ->
                    let
                        json =
                            """
                            { "id": "4834470a914c46088ea4576b48df68b3", "kind": "render"
                            , "status": "running", "fraction": 0.0, "message": ""
                            , "error": null, "result": null
                            , "song_id": "15ff79b16efd4fc58874df4eac097a38"
                            , "created_at": "2026-08-04T21:03:17.584296+00:00" }
                            """
                    in
                    case Decode.decodeString Api.job json of
                        Ok j ->
                            Expect.equal "2026-08-04T21:03:17.584296+00:00" j.createdAt

                        Err err ->
                            Expect.fail (Decode.errorToString err)
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
        ]
