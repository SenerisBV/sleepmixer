module Request exposing (importSong, loop, peaks, schema, song, songs, startSeparation)

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
