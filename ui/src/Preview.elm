module Preview exposing
    ( Params, State(..)
    , arrived, encode, isPlayable, request, warm, warmed
    )

{-| When to ask the server for a preview, and when not to.

Previews serialize per song — measured at 117 seconds cold and 73 milliseconds
warm — because the server holds a per-song lock across the whole render. A
scrubber drag emits dozens of events, so firing one request each would queue
dozens of renders behind one another and hold a threadpool thread for every
one of them.

So: at most one request in flight, and at most one waiting. A request that
arrives while one is in flight *replaces* whatever was waiting rather than
joining a queue — by the time the server answers, the intermediate positions
are of no interest to anyone.

This lives in Elm rather than in the port module because it is the only part
of the audio path that can be tested. `ports/audio.js` executes what this
decides and decides nothing.
-}

import Json.Encode as Encode


type alias Params =
    { songId : String
    , progress : Float
    , stems : List String
    , config : Encode.Value
    }


{-| The request body `POST /api/preview` actually expects.

The record uses Elm's naming and the API uses Python's, so this cannot be a
`JSON.stringify` of the record — `songId` would arrive as `songId` and the
endpoint would reject it. `stems` is omitted rather than sent empty, because
the server treats a missing `stems` as "every stem the render would process"
while an empty list means "none", which would preview silence.
-}
encode : Params -> Encode.Value
encode params =
    Encode.object
        ([ ( "song_id", Encode.string params.songId )
         , ( "progress", Encode.float params.progress )
         , ( "config", params.config )
         ]
            ++ (if List.isEmpty params.stems then
                    []

                else
                    [ ( "stems", Encode.list Encode.string params.stems ) ]
               )
        )


type State
    = Cold
    | Warming
    | Idle
    | InFlight Params
    | Queued Params


{-| Playable once the first preview has returned. Until then the session may
still be building stems and a stretched loop, which is the 117-second path.
-}
isPlayable : State -> Bool
isPlayable state =
    case state of
        Cold ->
            False

        Warming ->
            False

        Idle ->
            True

        InFlight _ ->
            True

        Queued _ ->
            True


{-| The one request no control asks for: opening the mixer.

`request` refuses to send while `Cold` — that is the whole point of `Cold`, and
it is what stops a control change firing a request into a session that has no
stems yet. But *something* has to make the first call, because the cold render
is also what calibrates `master_gain`, and until it has happened every later
preview would play at a level the finished mix never reaches.

It lives here rather than in `Main` for the reason the rest of this module
does: it is a decision about whether to send, and every one of those is
testable only while it stays on this side of the port. Entering a mixer that is
already warm sends nothing, so re-opening a song costs no render at all.
-}
warm : Params -> State -> ( State, Maybe Params )
warm params state =
    case state of
        Cold ->
            ( Warming, Just params )

        other ->
            ( other, Nothing )


warmed : State -> State
warmed state =
    case state of
        Warming ->
            Idle

        other ->
            other


{-| Returns the next state and, when there is one, the request to actually send.
-}
request : Params -> State -> ( State, Maybe Params )
request params state =
    case state of
        Cold ->
            ( Cold, Nothing )

        Warming ->
            ( Warming, Nothing )

        Idle ->
            ( InFlight params, Just params )

        InFlight _ ->
            ( Queued params, Nothing )

        Queued _ ->
            -- Latest wins: the position the user has already moved past is of
            -- no interest by the time the server answers.
            ( Queued params, Nothing )


{-| Call when a preview returns, whether it succeeded or failed — either way
the slot is free and anything waiting should go now.
-}
arrived : State -> ( State, Maybe Params )
arrived state =
    case state of
        Queued pending ->
            ( InFlight pending, Just pending )

        InFlight _ ->
            ( Idle, Nothing )

        other ->
            ( other, Nothing )
