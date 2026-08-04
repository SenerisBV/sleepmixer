module Preview exposing
    ( Params, State(..)
    , arrived, encode, failed, isPlayable, request, retry, warm, warmed
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
testable only while it stays on this side of the port.

Nothing here spares the request: leaving the mixer resets this to `Cold`, so
re-opening a song sends another opening preview. What is saved is on the
server, where the session — separated stems, detected loop, stretched loops —
is still warm and answers in milliseconds rather than minutes. `Warming` is a
statement about this application's knowledge, not about the server's.
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


{-| Call when a preview plays: the slot is free and anything waiting goes now.

For a preview that *failed*, call `failed` instead. Both are exactly one call
per request emitted, which is what `ports/audio.js` is written against; they
differ only in what a failure means for the opening preview.
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


{-| Call when a preview comes back failed.

For an ordinary request this is `arrived`: the slot is free either way, and a
failure at one scrubber position says nothing about the next.

The opening preview is different. It is the only thing that establishes there
is anything to play — stems, a stretched loop, a calibrated master gain — and
if it did not come back, none of that is known to exist. Treating it as
`arrived` would move `Warming` to `Idle`, which is `isPlayable`, which replaces
the preparing panel with a live scrubber and enabled sliders over silence. So a
failed opening preview goes back to `Cold`: not playable, sending nothing, and
`warm` (via `retry`) is the way out. Nothing can be queued behind it, because
`request` refuses while `Warming`.
-}
failed : State -> ( State, Maybe Params )
failed state =
    case state of
        Warming ->
            ( Cold, Nothing )

        other ->
            arrived other


{-| Asking again, by hand, after something went wrong.

The same two doors as everything else, chosen by which side of the opening
preview the failure happened on.
-}
retry : Params -> State -> ( State, Maybe Params )
retry params state =
    case state of
        Cold ->
            warm params state

        _ ->
            request params state
