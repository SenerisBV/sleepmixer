module Waveform exposing (Bar, barFor, view)

{-| Peaks as SVG.

SVG rather than canvas because a canvas would mean escaping Elm's virtual DOM
and managing pixels through a port, while the loop-region handles this needs
are just mouse events mapped to messages — which is a state machine Elm models
well. A few thousand rects is well within what a browser draws comfortably.

Min *and* max are drawn rather than absolute peak, so an asymmetric signal
looks asymmetric. That is a real cue when picking a loop region by eye.
-}

import Svg exposing (Svg)
import Svg.Attributes as A


type alias Bar =
    { y : Float, height : Float }


{-| Where one peak pair sits in a viewport of the given height.

The vertical axis is inverted — SVG grows downward, audio does not — so a peak
of +1.0 is at y=0. A silent bucket still gets a hairline: a waveform with holes
in it reads as missing data rather than as silence.
-}
barFor : { height : Float } -> ( Float, Float ) -> Bar
barFor { height } ( low, high ) =
    let
        clamp value =
            Basics.max -1.0 (Basics.min 1.0 value)

        toY value =
            (1.0 - clamp value) / 2.0 * height

        top =
            toY (clamp high)

        bottom =
            toY (clamp low)
    in
    { y = top, height = Basics.max 1.0 (bottom - top) }


view :
    { peaks : List ( Float, Float )
    , width : Float
    , height : Float
    , loop : Maybe { start : Float, end : Float }
    }
    -> Svg msg
view config =
    let
        count =
            List.length config.peaks

        barWidth =
            if count == 0 then
                0

            else
                config.width / toFloat count

        bar index pair =
            let
                { y, height } =
                    barFor { height = config.height } pair
            in
            Svg.rect
                [ A.x (String.fromFloat (toFloat index * barWidth))
                , A.y (String.fromFloat y)
                , A.width (String.fromFloat (Basics.max 0.5 (barWidth - 0.2)))
                , A.height (String.fromFloat height)
                , A.fill "#7aa2f7"
                ]
                []
    in
    Svg.svg
        [ A.viewBox ("0 0 " ++ String.fromFloat config.width ++ " " ++ String.fromFloat config.height)
        , A.width "100%"
        , A.height (String.fromFloat config.height)
        , A.class "waveform"
        ]
        (loopRegion config ++ List.indexedMap bar config.peaks)


loopRegion :
    { a
        | width : Float
        , height : Float
        , loop : Maybe { start : Float, end : Float }
    }
    -> List (Svg msg)
loopRegion config =
    case config.loop of
        Nothing ->
            []

        Just { start, end } ->
            [ Svg.rect
                [ A.x (String.fromFloat (start * config.width))
                , A.y "0"
                , A.width (String.fromFloat ((end - start) * config.width))
                , A.height (String.fromFloat config.height)
                , A.fill "#7aa2f7"
                , A.opacity "0.14"
                ]
                []
            ]
