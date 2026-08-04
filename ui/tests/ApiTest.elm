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
                            , "error": null, "result": null, "song_id": "abc" }
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
                            , "result": null, "song_id": "abc" }
                            """
                    in
                    case Decode.decodeString Api.job json of
                        Ok j ->
                            Expect.equal (Api.Failed "RuntimeError: disk full") j.status

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
        ]
