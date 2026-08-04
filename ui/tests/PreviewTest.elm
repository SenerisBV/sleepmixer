module PreviewTest exposing (suite)

import Expect
import Json.Encode as Encode
import Preview
import Test exposing (Test, describe, test)


params : Float -> Preview.Params
params progress =
    { songId = "s1"
    , progress = progress
    , stems = []
    , config = Encode.object []
    }


suite : Test
suite =
    describe "Preview"
        [ describe "warming"
            [ test "a cold session is not playable" <|
                \_ -> Expect.equal False (Preview.isPlayable Preview.Cold)
            , test "a warming session is not playable" <|
                \_ -> Expect.equal False (Preview.isPlayable Preview.Warming)
            , test "an idle session is playable" <|
                \_ -> Expect.equal True (Preview.isPlayable Preview.Idle)
            , test "warmed moves Warming to Idle" <|
                \_ -> Expect.equal Preview.Idle (Preview.warmed Preview.Warming)
            ]
        , describe "request"
            [ test "an idle session sends immediately" <|
                \_ ->
                    Preview.request (params 0.5) Preview.Idle
                        |> Expect.equal ( Preview.InFlight (params 0.5), Just (params 0.5) )
            , test "a request while in flight is queued, not sent" <|
                \_ ->
                    Preview.request (params 0.6) (Preview.InFlight (params 0.5))
                        |> Expect.equal
                            ( Preview.Queued (params 0.5) (params 0.6), Nothing )
            , test "a second queued request replaces the first — latest wins" <|
                \_ ->
                    Preview.request (params 0.7)
                        (Preview.Queued (params 0.5) (params 0.6))
                        |> Expect.equal
                            ( Preview.Queued (params 0.5) (params 0.7), Nothing )
            , test "a cold session does not send" <|
                \_ ->
                    Preview.request (params 0.5) Preview.Cold
                        |> Expect.equal ( Preview.Cold, Nothing )
            ]
        , describe "arrived"
            [ test "an in-flight result with nothing queued goes idle" <|
                \_ ->
                    Preview.arrived (Preview.InFlight (params 0.5))
                        |> Expect.equal ( Preview.Idle, Nothing )
            , test "a queued request is sent when the in-flight one returns" <|
                \_ ->
                    Preview.arrived (Preview.Queued (params 0.5) (params 0.7))
                        |> Expect.equal
                            ( Preview.InFlight (params 0.7), Just (params 0.7) )
            , test "arriving while idle changes nothing" <|
                \_ ->
                    Preview.arrived Preview.Idle
                        |> Expect.equal ( Preview.Idle, Nothing )
            ]
        , describe "encode"
            [ test "keys are the API's, not Elm's" <|
                \_ ->
                    let
                        json =
                            Encode.encode 0 (Preview.encode (params 0.5))
                    in
                    json
                        |> Expect.all
                            [ \s -> Expect.equal True (String.contains "\"song_id\"" s)
                            , \s -> Expect.equal False (String.contains "\"songId\"" s)
                            ]
            , test "an empty stems list is omitted, not sent empty" <|
                \_ ->
                    Encode.encode 0 (Preview.encode (params 0.5))
                        |> String.contains "\"stems\""
                        |> Expect.equal False
            , test "a non-empty stems list is included" <|
                \_ ->
                    let
                        withStems =
                            let
                                base =
                                    params 0.5
                            in
                            { base | stems = [ "vocals", "drums" ] }

                        json =
                            Encode.encode 0 (Preview.encode withStems)
                    in
                    json
                        |> Expect.all
                            [ \s -> Expect.equal True (String.contains "\"stems\"" s)
                            , \s -> Expect.equal True (String.contains "\"vocals\"" s)
                            , \s -> Expect.equal True (String.contains "\"drums\"" s)
                            ]
            ]
        , describe "the property that matters"
            [ test "a drag of twenty positions sends at most two requests" <|
                \_ ->
                    let
                        drag state sent position =
                            let
                                ( next, toSend ) =
                                    Preview.request (params position) state
                            in
                            ( next
                            , case toSend of
                                Just _ ->
                                    sent + 1

                                Nothing ->
                                    sent
                            )

                        ( _, count ) =
                            List.foldl
                                (\p ( s, n ) -> drag s n p)
                                ( Preview.Idle, 0 )
                                (List.map (\i -> toFloat i / 20) (List.range 0 19))
                    in
                    -- One goes out immediately; the other nineteen collapse into
                    -- a single pending request that only leaves once the first
                    -- returns. Without this the server queues twenty renders.
                    Expect.equal 1 count
            ]
        ]
