module Request exposing
    ( cancelJob, createPreset, defaultConfig, deletePreset, deleteRender, importSong
    , jobs, loop, peaks, presets, renders, schema, setLastPreset, song, songs
    , startRender, startSeparation, updatePreset
    )

{-| Every HTTP call the application makes, in one place.

Endpoints live here rather than beside the screens that use them so that a
change to the API surface is a change to one file, and so the compiler can
point at every caller when a signature moves.

URLs are built with `Url.Builder`, which percent-encodes each path segment and
query value, rather than concatenated. Nothing here is exploitable today — a
song id is server-generated opaque hex, never user input — but concatenation is
the kind of pattern that stops being safe the moment something less controlled
is threaded through it, and there is no cost to not having it.
-}

import Api
import Http
import Json.Decode as Decode
import Json.Encode as Encode
import Schema
import Url.Builder


songs : (Result Http.Error (List Api.Song) -> msg) -> Cmd msg
songs toMsg =
    Http.get
        { url = Url.Builder.absolute [ "api", "songs" ] []
        , expect = Http.expectJson toMsg (Decode.field "songs" (Decode.list Api.song))
        }


song : String -> (Result Http.Error Api.Song -> msg) -> Cmd msg
song songId toMsg =
    Http.get
        { url = Url.Builder.absolute [ "api", "songs", songId ] []
        , expect = Http.expectJson toMsg Api.song
        }


importSong : String -> (Result Http.Error Api.Song -> msg) -> Cmd msg
importSong path toMsg =
    Http.post
        { url = Url.Builder.absolute [ "api", "songs" ] []
        , body = Http.jsonBody (Encode.object [ ( "path", Encode.string path ) ])
        , expect = Http.expectJson toMsg Api.song
        }


startSeparation : String -> Bool -> (Result Http.Error Api.Job -> msg) -> Cmd msg
startSeparation songId force toMsg =
    Http.post
        { url =
            Url.Builder.absolute [ "api", "songs", songId, "separate" ]
                (if force then
                    [ Url.Builder.string "force" "true" ]

                 else
                    []
                )
        , body = Http.emptyBody
        , expect = Http.expectJson toMsg Api.job
        }


schema : (Result Http.Error Schema.Schema -> msg) -> Cmd msg
schema toMsg =
    Http.get
        { url = Url.Builder.absolute [ "api", "schema" ] []
        , expect = Http.expectJson toMsg Schema.decoder
        }


{-| The loop region a render would use, in seconds, with the tempo it implies.

The overrides are the same two values `loop.start_s` and `loop.end_s` carry in
the config, and passing them asks the server to echo that region back with a
tempo rather than detect one — so the region drawn on the waveform stays the
region a render would actually loop. Passing neither asks for detection.

Note what the endpoint does *not* take: `bars`, `beats_per_bar` and the search
window are config fields a render honours and this call cannot express, so a
detected region here is detected under `LoopConfig`'s defaults.
-}
loop :
    String
    -> { startS : Maybe Float, endS : Maybe Float }
    -> (Result Http.Error Api.LoopRegion -> msg)
    -> Cmd msg
loop songId override toMsg =
    Http.get
        { url =
            Url.Builder.absolute [ "api", "songs", songId, "loop" ]
                (List.filterMap identity
                    [ Maybe.map (Url.Builder.string "start_s" << String.fromFloat) override.startS
                    , Maybe.map (Url.Builder.string "end_s" << String.fromFloat) override.endS
                    ]
                )
        , expect = Http.expectJson toMsg Api.loopRegion
        }


peaks : String -> Int -> (Result Http.Error (List ( Float, Float )) -> msg) -> Cmd msg
peaks songId buckets toMsg =
    Http.get
        { url =
            Url.Builder.absolute [ "api", "songs", songId, "peaks" ]
                [ Url.Builder.int "buckets" buckets ]
        , expect =
            Http.expectJson toMsg
                (Decode.field "peaks"
                    (Decode.list
                        (Decode.map2 Tuple.pair
                            (Decode.index 0 Decode.float)
                            (Decode.index 1 Decode.float)
                        )
                    )
                )
        }


renders : (Result Http.Error (List Api.Render) -> msg) -> Cmd msg
renders toMsg =
    Http.get
        { url = Url.Builder.absolute [ "api", "renders" ] []
        , expect = Http.expectJson toMsg (Decode.field "renders" (Decode.list Api.render))
        }


{-| Start a full mix render for a song under the given config.

`POST /api/renders` answers 202 with `{"job": ..., "render": ...}` — the row it
creates up front so the UI has something to show even before the worker picks
the job up. This decodes just the `job` field out of that envelope, matching
what `startSeparation` already returns for the same reason: the caller tracks
progress through the job, and can fetch the render row separately once it
wants to.
-}
startRender : String -> Encode.Value -> (Result Http.Error Api.Job -> msg) -> Cmd msg
startRender songId config toMsg =
    Http.post
        { url = Url.Builder.absolute [ "api", "renders" ] []
        , body =
            Http.jsonBody
                (Encode.object
                    [ ( "song_id", Encode.string songId )
                    , ( "config", config )
                    ]
                )
        , expect = Http.expectJson toMsg (Decode.field "job" Api.job)
        }


{-| Remove a render and its file.

`DELETE /api/renders/{id}` answers 204 with no body, so this goes through
`Http.request` with `Http.expectWhatever` rather than `Http.post` with
`expectJson` — `expectJson` would fail trying to parse an empty response as
JSON.
-}
deleteRender : String -> (Result Http.Error () -> msg) -> Cmd msg
deleteRender renderId toMsg =
    Http.request
        { method = "DELETE"
        , headers = []
        , url = Url.Builder.absolute [ "api", "renders", renderId ] []
        , body = Http.emptyBody
        , expect = Http.expectWhatever toMsg
        , timeout = Nothing
        , tracker = Nothing
        }


jobs : (Result Http.Error (List Api.Job) -> msg) -> Cmd msg
jobs toMsg =
    Http.get
        { url = Url.Builder.absolute [ "api", "jobs" ] []
        , expect = Http.expectJson toMsg (Decode.field "jobs" (Decode.list Api.job))
        }


{-| Ask a job to stop, and hear back both halves of the answer.

`cancelled` is the server's own report of whether there was anything left to
stop, and it is not derivable from the job beside it. The route calls
`JobManager.cancel` and then re-`get`s the job, so a job that was genuinely
cancelled can come back already `done` if the worker finished it in that
window — reading the status alone would then tell the user "nothing was
stopped" about a cancel that worked. Only `cancelled` distinguishes the two,
and it is the field the route exists to return.
-}
cancelJob : String -> (Result Http.Error Api.Cancellation -> msg) -> Cmd msg
cancelJob jobId toMsg =
    Http.post
        { url = Url.Builder.absolute [ "api", "jobs", jobId, "cancel" ] []
        , body = Http.emptyBody
        , expect = Http.expectJson toMsg Api.cancellation
        }


presets : (Result Http.Error (List Api.Preset) -> msg) -> Cmd msg
presets toMsg =
    Http.get
        { url = Url.Builder.absolute [ "api", "presets" ] []
        , expect = Http.expectJson toMsg (Decode.field "presets" (Decode.list Api.preset))
        }


createPreset : String -> Encode.Value -> (Result Http.Error Api.Preset -> msg) -> Cmd msg
createPreset name config toMsg =
    Http.post
        { url = Url.Builder.absolute [ "api", "presets" ] []
        , body =
            Http.jsonBody
                (Encode.object
                    [ ( "name", Encode.string name )
                    , ( "config", config )
                    ]
                )
        , expect = Http.expectJson toMsg Api.preset
        }


updatePreset : String -> String -> Encode.Value -> (Result Http.Error Api.Preset -> msg) -> Cmd msg
updatePreset presetId name config toMsg =
    Http.request
        { method = "PUT"
        , headers = []
        , url = Url.Builder.absolute [ "api", "presets", presetId ] []
        , body =
            Http.jsonBody
                (Encode.object
                    [ ( "name", Encode.string name )
                    , ( "config", config )
                    ]
                )
        , expect = Http.expectJson toMsg Api.preset
        , timeout = Nothing
        , tracker = Nothing
        }


{-| Remove a preset.

`DELETE /api/presets/{id}` answers 204 with no body, exactly like
`deleteRender`, so this goes through `Http.request` with `Http.expectWhatever`
rather than `Http.post` with `expectJson` — `expectJson` would report a
successful delete as an error trying to parse the empty body as JSON.
-}
deletePreset : String -> (Result Http.Error () -> msg) -> Cmd msg
deletePreset presetId toMsg =
    Http.request
        { method = "DELETE"
        , headers = []
        , url = Url.Builder.absolute [ "api", "presets", presetId ] []
        , body = Http.emptyBody
        , expect = Http.expectWhatever toMsg
        , timeout = Nothing
        , tracker = Nothing
        }


{-| The full default `MixConfig`, as a plain value — the starting point for a
new preset, and for "reset to defaults" in the mixer. Nothing here needs a
typed record: it is handed straight back to the server as a `config` on the
next save or render, never read field-by-field on this side.
-}
defaultConfig : (Result Http.Error Decode.Value -> msg) -> Cmd msg
defaultConfig toMsg =
    Http.get
        { url = Url.Builder.absolute [ "api", "config", "default" ] []
        , expect = Http.expectJson toMsg Decode.value
        }


{-| Remember (or clear) which preset a song last had applied.

`Nothing` encodes as a JSON `null`, not as an omitted `preset_id` key — the
route's model defaults a missing key to `None` today, so both happen to
arrive the same way, but sending `null` says what is meant instead of leaning
on that default.
-}
setLastPreset : String -> Maybe String -> (Result Http.Error Api.Song -> msg) -> Cmd msg
setLastPreset songId presetId toMsg =
    Http.request
        { method = "PUT"
        , headers = []
        , url = Url.Builder.absolute [ "api", "songs", songId, "last-preset" ] []
        , body =
            Http.jsonBody
                (Encode.object
                    [ ( "preset_id", Maybe.withDefault Encode.null (Maybe.map Encode.string presetId) )
                    ]
                )
        , expect = Http.expectJson toMsg Api.song
        , timeout = Nothing
        , tracker = Nothing
        }
