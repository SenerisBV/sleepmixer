module WaveformTest exposing (suite)

import Expect
import Test exposing (Test, describe, test)
import Waveform


suite : Test
suite =
    describe "Waveform"
        [ test "maps a peak pair to a vertical extent within the viewport" <|
            \_ ->
                Waveform.barFor { height = 100 } ( -1.0, 1.0 )
                    |> Expect.all
                        [ .y >> Expect.within (Expect.Absolute 0.01) 0
                        , .height >> Expect.within (Expect.Absolute 0.01) 100
                        ]
        , test "silence becomes a hairline, not nothing" <|
            \_ ->
                Waveform.barFor { height = 100 } ( 0.0, 0.0 )
                    |> .height
                    |> Expect.atLeast 1.0
        , test "an asymmetric peak stays asymmetric" <|
            \_ ->
                let
                    bar =
                        Waveform.barFor { height = 100 } ( -0.1, 0.9 )
                in
                Expect.lessThan 50 bar.y
        , test "clamps a peak outside [-1, 1] rather than drawing outside the box" <|
            \_ ->
                Waveform.barFor { height = 100 } ( -4.0, 4.0 )
                    |> Expect.all
                        [ .y >> Expect.atLeast 0
                        , .height >> Expect.atMost 100
                        ]
        , describe "the loop region"
            [ test "seconds become pixels through the song's duration" <|
                \_ ->
                    -- The API answers in seconds and the drawing is in pixels.
                    -- Before this took a duration, the conversion was the
                    -- caller's to remember and passing seconds straight
                    -- through drew the region thousands of pixels off the
                    -- right-hand edge — no error, no region, nothing to see.
                    Waveform.regionBox { durationS = 200, width = 1000 }
                        { startS = 40, endS = 60 }
                        |> Expect.equal (Just { x = 200, width = 100 })
            , test "a region past the end of the track stops at the end" <|
                \_ ->
                    Waveform.regionBox { durationS = 200, width = 1000 }
                        { startS = 180, endS = 400 }
                        |> Expect.equal (Just { x = 900, width = 100 })
            , test "a song with no duration draws nothing rather than NaN" <|
                \_ ->
                    -- Dividing by it would emit `NaN` into an SVG attribute,
                    -- which browsers ignore silently.
                    Waveform.regionBox { durationS = 0, width = 1000 }
                        { startS = 40, endS = 60 }
                        |> Expect.equal Nothing
            , test "an empty region draws nothing" <|
                \_ ->
                    Waveform.regionBox { durationS = 200, width = 1000 }
                        { startS = 60, endS = 60 }
                        |> Expect.equal Nothing
            , test "a region entirely past the end draws nothing" <|
                \_ ->
                    Waveform.regionBox { durationS = 200, width = 1000 }
                        { startS = 300, endS = 400 }
                        |> Expect.equal Nothing
            ]
        ]
