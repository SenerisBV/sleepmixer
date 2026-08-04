module Waveform exposing (Bar, Box, barFor, regionBox, view)

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
    , durationS : Float
    , loop : Maybe { startS : Float, endS : Float }
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


type alias Box =
    { x : Float, width : Float }


{-| Where a stretch of *seconds* falls across a waveform of a given pixel width.

Seconds and a duration rather than the two fractions this used to take. The
fractions were the arithmetic the caller had to remember to do, and the API
that supplies a loop region — `GET /api/songs/{id}/loop` — answers in seconds:
handing those straight to a multiply-by-width drew the region several thousand
pixels off the right-hand edge, with no error anywhere, because nothing in
either type said which unit it wanted. Asking for the duration in the same
record is what makes that mistake fail to compile.

`Nothing` for a duration that is zero or negative (a song row with no duration
would otherwise divide by zero and emit `NaN` into an SVG attribute, which
browsers ignore silently) and for a region with no width. The result is clamped
to the drawing, so an override past the end of the track marks the end of the
track rather than running off it.
-}
regionBox : { durationS : Float, width : Float } -> { startS : Float, endS : Float } -> Maybe Box
regionBox canvas region =
    if canvas.durationS <= 0 || region.endS <= region.startS then
        Nothing

    else
        let
            toX seconds =
                clamp 0 canvas.width (seconds / canvas.durationS * canvas.width)

            left =
                toX region.startS

            right =
                toX region.endS
        in
        if right <= left then
            Nothing

        else
            Just { x = left, width = right - left }


loopRegion :
    { a
        | width : Float
        , height : Float
        , durationS : Float
        , loop : Maybe { startS : Float, endS : Float }
    }
    -> List (Svg msg)
loopRegion config =
    case Maybe.andThen (regionBox { durationS = config.durationS, width = config.width }) config.loop of
        Nothing ->
            []

        Just box ->
            [ Svg.rect
                [ A.x (String.fromFloat box.x)
                , A.y "0"
                , A.width (String.fromFloat box.width)
                , A.height (String.fromFloat config.height)
                , A.fill "#7aa2f7"
                , A.opacity "0.14"
                ]
                []
            ]
