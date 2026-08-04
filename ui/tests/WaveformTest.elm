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
        ]
