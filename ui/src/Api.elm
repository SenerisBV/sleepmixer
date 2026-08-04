module Api exposing
    ( Job, JobStatus(..), LoopRegion, Song, SeparationStatus(..)
    , isFinished, job, loopRegion, song, statusLabel
    )

{-| Types and decoders for the sleepmix API.

This is the seam where an untyped HTTP response becomes a typed value, and it
is deliberately strict: an unrecognised status fails the decode rather than
falling back to a catch-all. A server that grows a status this application does
not handle should say so loudly, not render an empty row.
-}

import Json.Decode as Decode exposing (Decoder)
import Json.Decode.Pipeline as Pipeline


type SeparationStatus
    = NotSeparated
    | Separating
    | Separated
    | Fallback String
    | SeparationFailed String


type alias Song =
    { id : String
    , path : String
    , title : String
    , durationS : Float
    , sampleRate : Int
    , separationStatus : SeparationStatus
    , stems : List String
    , addedAt : String
    }


{-| The stretch of the song a render will loop, and the tempo it was found at.

Seconds, because that is what `GET /api/songs/{id}/loop` returns and what the
`loop.start_s` / `loop.end_s` config fields take. Anything that wants a
fraction of the track divides by the song's duration at the point of use —
notably `Waveform.view`, which asks for both so the conversion cannot be
skipped by accident.
-}
type alias LoopRegion =
    { startS : Float
    , endS : Float
    , tempo : Float
    }


type JobStatus
    = Queued
    | Running
    | Done
    | Cancelled
    | Failed String


type alias Job =
    { id : String
    , kind : String
    , status : JobStatus
    , fraction : Float
    , message : String
    , songId : Maybe String
    }


isFinished : JobStatus -> Bool
isFinished status =
    case status of
        Queued ->
            False

        Running ->
            False

        Done ->
            True

        Cancelled ->
            True

        Failed _ ->
            True


statusLabel : SeparationStatus -> String
statusLabel status =
    case status of
        NotSeparated ->
            "not separated"

        Separating ->
            "separating…"

        Separated ->
            "separated"

        Fallback _ ->
            "one stem only"

        SeparationFailed _ ->
            "separation failed"


song : Decoder Song
song =
    Decode.succeed Song
        |> Pipeline.required "id" Decode.string
        |> Pipeline.required "path" Decode.string
        |> Pipeline.required "title" Decode.string
        |> Pipeline.required "duration_s" Decode.float
        |> Pipeline.required "sample_rate" Decode.int
        |> Pipeline.custom separationStatus
        |> Pipeline.optional "stems" (Decode.nullable (Decode.list Decode.string) |> Decode.map (Maybe.withDefault [])) []
        |> Pipeline.required "added_at" Decode.string


separationStatus : Decoder SeparationStatus
separationStatus =
    Decode.map2 Tuple.pair
        (Decode.field "separation_status" Decode.string)
        (Decode.field "separation_reason" (Decode.nullable Decode.string))
        |> Decode.andThen
            (\( status, reason ) ->
                case status of
                    "pending" ->
                        Decode.succeed NotSeparated

                    "running" ->
                        Decode.succeed Separating

                    "done" ->
                        Decode.succeed Separated

                    "fallback" ->
                        Decode.succeed (Fallback (Maybe.withDefault "no reason given" reason))

                    "failed" ->
                        Decode.succeed (SeparationFailed (Maybe.withDefault "no reason given" reason))

                    other ->
                        Decode.fail ("unknown separation_status: " ++ other)
            )


loopRegion : Decoder LoopRegion
loopRegion =
    Decode.map3 LoopRegion
        (Decode.field "start_s" Decode.float)
        (Decode.field "end_s" Decode.float)
        (Decode.field "tempo" Decode.float)


job : Decoder Job
job =
    Decode.succeed Job
        |> Pipeline.required "id" Decode.string
        |> Pipeline.required "kind" Decode.string
        |> Pipeline.custom jobStatus
        |> Pipeline.required "fraction" Decode.float
        |> Pipeline.required "message" Decode.string
        |> Pipeline.required "song_id" (Decode.nullable Decode.string)


jobStatus : Decoder JobStatus
jobStatus =
    Decode.map2 Tuple.pair
        (Decode.field "status" Decode.string)
        (Decode.field "error" (Decode.nullable Decode.string))
        |> Decode.andThen
            (\( status, err ) ->
                case status of
                    "queued" ->
                        Decode.succeed Queued

                    "running" ->
                        Decode.succeed Running

                    "done" ->
                        Decode.succeed Done

                    "cancelled" ->
                        Decode.succeed Cancelled

                    "failed" ->
                        Decode.succeed (Failed (Maybe.withDefault "no detail given" err))

                    other ->
                        Decode.fail ("unknown job status: " ++ other)
            )
