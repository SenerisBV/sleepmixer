module Api exposing
    ( Job, JobStatus(..), LoopRegion, Render, RenderStatus(..), Song, SeparationStatus(..)
    , isFinished, isRenderFinished, job, loopRegion, render, renderStatusLabel, song, statusLabel
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
    , createdAt : String
    }


{-| The status of a full mix render.

Mirrors `RenderStatus` on the server (`sleepmix/server/store.py`'s `renders`
table): a render row starts `queued`, moves to `running`, and ends at exactly
one of `done`, `failed` or `cancelled` — never both failed and cancelled, even
when the pipeline throws after the cancel token was already set (the server
classifies by exception type, not by the token, so the two rows always agree).
-}
type RenderStatus
    = RenderQueued
    | RenderRunning
    | RenderDone
    | RenderFailed
    | RenderCancelled


{-| A render's row, as `GET /api/renders` and `GET /api/renders/{id}` return
it.

`config` stays an opaque `Decode.Value` rather than a typed record: it is
whatever `MixConfig` produced for this render, echoed back by the server as a
real JSON object (`store._render_from_row` does `json.loads` on the column
before the route ever sees it — it is not a string of JSON to parse again).
Nothing here needs to read inside it; `path`, `status` and `durationMin` are
what a renders list or a queue screen shows.

`durationMin` is `Nothing` until the render finishes — the column is `NULL` in
SQLite until `POST /api/renders`'s background work sets it alongside
`status = "done"`.
-}
type alias Render =
    { id : String
    , songId : String
    , status : RenderStatus
    , path : String
    , durationMin : Maybe Float
    , config : Decode.Value
    , createdAt : String
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


isRenderFinished : RenderStatus -> Bool
isRenderFinished status =
    case status of
        RenderQueued ->
            False

        RenderRunning ->
            False

        RenderDone ->
            True

        RenderFailed ->
            True

        RenderCancelled ->
            True


renderStatusLabel : RenderStatus -> String
renderStatusLabel status =
    case status of
        RenderQueued ->
            "queued"

        RenderRunning ->
            "rendering…"

        RenderDone ->
            "done"

        RenderFailed ->
            "failed"

        RenderCancelled ->
            "cancelled"


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
        |> Pipeline.required "created_at" Decode.string


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


render : Decoder Render
render =
    Decode.succeed Render
        |> Pipeline.required "id" Decode.string
        |> Pipeline.required "song_id" Decode.string
        |> Pipeline.custom renderStatus
        |> Pipeline.required "path" Decode.string
        |> Pipeline.required "duration_min" (Decode.nullable Decode.float)
        |> Pipeline.required "config" Decode.value
        |> Pipeline.required "created_at" Decode.string


renderStatus : Decoder RenderStatus
renderStatus =
    Decode.field "status" Decode.string
        |> Decode.andThen
            (\status ->
                case status of
                    "queued" ->
                        Decode.succeed RenderQueued

                    "running" ->
                        Decode.succeed RenderRunning

                    "done" ->
                        Decode.succeed RenderDone

                    "failed" ->
                        Decode.succeed RenderFailed

                    "cancelled" ->
                        Decode.succeed RenderCancelled

                    other ->
                        Decode.fail ("unknown render status: " ++ other)
            )
