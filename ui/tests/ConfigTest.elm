module ConfigTest exposing (suite)

{-| What the mixer actually sends.

A wrong config here is the worst kind of bug this branch can produce: the
preview plays, it sounds like something, and it is a preview of a mix nobody
asked for. So these assert on the *shape the server reads* — decoding the
encoder's output back out along the paths `MixConfig.from_dict` walks — rather
than on a golden string, which would fail on key order and pass on a value
landing one level too high.

-}

import Config
import Expect exposing (Expectation)
import Fixtures
import Json.Decode as Decode
import Test exposing (Test, describe, test)


{-| A mixer opened on a song separated into three stems.
-}
config : Config.Config
config =
    Config.fromSchema Fixtures.schema [ "vocals", "drums", "bass" ]


decode : Decode.Decoder a -> Config.Config -> Result Decode.Error a
decode decoder value =
    Decode.decodeValue decoder (Config.encode value)


expect : Decode.Decoder a -> a -> Config.Config -> Expectation
expect decoder expected value =
    decode decoder value |> Expect.equal (Ok expected)


{-| The keys actually present under an object, sorted. Absence is the whole
point of several of these tests, and a decoder for one key cannot tell "not
sent" from "sent as null".
-}
keysOf : Decode.Decoder (List String)
keysOf =
    Decode.map (List.map Tuple.first >> List.sort) (Decode.keyValuePairs Decode.value)


stemAt : Int -> Decode.Decoder a -> Decode.Decoder a
stemAt index decoder =
    Decode.field "stems" (Decode.index index decoder)


stemField : Int -> String -> Decode.Decoder a -> Decode.Decoder a
stemField index key decoder =
    stemAt index (Decode.field key decoder)


suite : Test
suite =
    describe "Config"
        [ describe "the config a fresh mixer sends"
            [ test "carries the top-level scalars" <|
                \_ ->
                    config
                        |> Expect.all
                            [ expect (Decode.field "seed" Decode.int) 0
                            , expect (Decode.field "separation_model" Decode.string) "htdemucs_ft"
                            ]
            , test "nests each section under its own key" <|
                \_ ->
                    config
                        |> Expect.all
                            [ expect (Decode.at [ "loop", "bars" ] Decode.int) 8
                            , expect (Decode.at [ "tempo", "speed" ] Decode.float) 0.7
                            , expect (Decode.at [ "output", "sample_rate" ] Decode.int) 44100
                            , expect (Decode.at [ "soundbed", "enabled" ] Decode.bool) False
                            ]
            , test "carries one stem per separated stem, named" <|
                \_ ->
                    config
                        |> expect
                            (Decode.field "stems" (Decode.list (Decode.field "name" Decode.string)))
                            [ "vocals", "drums", "bass" ]
            , test "gives each stem its own decay object" <|
                \_ ->
                    config
                        |> Expect.all
                            [ expect (stemField 0 "enabled" Decode.bool) True
                            , expect (stemField 0 "gain_db" Decode.float) 0.0
                            , expect (stemField 0 "reverb_send" Decode.float) 1.0
                            , expect
                                (stemField 0 "decay" (Decode.field "curve" Decode.string))
                                "linear"
                            , expect
                                (stemField 0 "decay" (Decode.field "lowpass_start_hz" Decode.float))
                                18000.0
                            ]
            , test "does not send the per-stem sections as global ones" <|
                \_ ->
                    -- `stem` and `stem_decay` describe the elements of a list.
                    -- Sent as top-level keys they would be ignored by
                    -- `_build`'s unknown-key skip — silently, which is worse
                    -- than an error.
                    config
                        |> expect keysOf
                            [ "loop", "output", "seed", "separation_model", "soundbed", "stems", "tempo" ]
            , test "leaves a field whose default is null absent, not zeroed" <|
                \_ ->
                    -- `loop.start_s` absent means "detect the loop"; sent as
                    -- 0.0 it means "start the loop at the first sample", and
                    -- nothing downstream could tell the two apart.
                    config
                        |> expect (Decode.field "loop" keysOf)
                            [ "bars", "crossfade_ms", "search_start" ]
            ]
        , describe "editing a stem"
            [ test "a gain change lands on that stem and no other" <|
                \_ ->
                    config
                        |> Config.set Fixtures.schema (Config.InStem 1 "gain_db") "-6.5"
                        |> Expect.all
                            [ expect (stemField 1 "gain_db" Decode.float) -6.5
                            , expect (stemField 0 "gain_db" Decode.float) 0.0
                            , expect (stemField 2 "gain_db" Decode.float) 0.0
                            ]
            , test "disabling a stem is what the config says" <|
                \_ ->
                    config
                        |> Config.toggle (Config.InStem 2 "enabled") False
                        |> Expect.all
                            [ expect (stemField 2 "enabled" Decode.bool) False
                            , expect (stemField 0 "enabled" Decode.bool) True
                            ]
            , test "a decay edit lands under decay, not beside it" <|
                \_ ->
                    -- One level too high and `_build` drops it as an unknown
                    -- key on `StemConfig`, leaving the decay at its default
                    -- with nothing said about it.
                    config
                        |> Config.set Fixtures.schema (Config.InStemDecay 0 "amp_end_db") "-20"
                        |> Expect.all
                            [ expect
                                (stemField 0 "decay" (Decode.field "amp_end_db" Decode.float))
                                -20.0
                            , expect (stemAt 0 keysOf)
                                [ "decay", "enabled", "gain_db", "name", "reverb_send" ]
                            ]
            , test "a curve outside the schema's choices is refused" <|
                \_ ->
                    config
                        |> Config.set Fixtures.schema (Config.InStemDecay 0 "curve") "sawtooth"
                        |> expect
                            (stemField 0 "decay" keysOf)
                            [ "amp_end_db", "enabled", "lowpass_start_hz" ]
            ]
        , describe "bounds"
            [ test "a negative seed cannot be constructed from the UI's own controls" <|
                \_ ->
                    -- `MixConfig.validate` raises on one, so a control able to
                    -- produce it turns a slider into a 400. The floor comes
                    -- from the schema, not from a special case for `seed`.
                    config
                        |> Config.set Fixtures.schema (Config.Top "seed") "-5"
                        |> expect (Decode.field "seed" Decode.int) 0
            , test "nor by way of a fraction that rounds below zero" <|
                \_ ->
                    config
                        |> Config.set Fixtures.schema (Config.Top "seed") "-0.4"
                        |> expect (Decode.field "seed" Decode.int) 0
            , test "a seed stays an integer" <|
                \_ ->
                    -- numpy's SeedSequence refuses a float outright.
                    config
                        |> Config.set Fixtures.schema (Config.Top "seed") "7.9"
                        |> expect (Decode.field "seed" Decode.int) 8
            , test "a value above the schema's maximum is clamped, not sent" <|
                \_ ->
                    config
                        |> Config.set Fixtures.schema (Config.InStem 0 "gain_db") "99"
                        |> expect (stemField 0 "gain_db" Decode.float) 12.0
            , test "a value below the schema's minimum is clamped, not sent" <|
                \_ ->
                    config
                        |> Config.set Fixtures.schema (Config.InSection "tempo" "speed") "0"
                        |> expect (Decode.at [ "tempo", "speed" ] Decode.float) 0.05
            ]
        , describe "clearing a field"
            [ test "an emptied nullable field goes back to absent" <|
                \_ ->
                    config
                        |> Config.set Fixtures.schema (Config.InSection "loop" "start_s") "12.5"
                        |> Config.set Fixtures.schema (Config.InSection "loop" "start_s") ""
                        |> expect (Decode.field "loop" keysOf)
                            [ "bars", "crossfade_ms", "search_start" ]
            , test "an emptied text field falls back to the server's default" <|
                \_ ->
                    -- Not the empty string: `separation_model` is a text
                    -- field, and `""` arrives at Demucs as a model name.
                    config
                        |> Config.set Fixtures.schema (Config.Top "separation_model") "  "
                        |> expect keysOf
                            [ "loop", "output", "seed", "soundbed", "stems", "tempo" ]
            , test "and setting one puts it back" <|
                \_ ->
                    config
                        |> Config.set Fixtures.schema (Config.InSection "loop" "start_s") "12.5"
                        |> expect (Decode.at [ "loop", "start_s" ] Decode.float) 12.5
            ]
        , describe "reading a value back for a control"
            [ test "a value that was set" <|
                \_ ->
                    config
                        |> Config.set Fixtures.schema (Config.InStem 1 "gain_db") "-6.5"
                        |> Config.valueAt (Config.InStem 1 "gain_db")
                        |> Expect.equal (Just (Config.FloatValue -6.5))
            , test "a value that never had a default" <|
                \_ ->
                    config
                        |> Config.valueAt (Config.InSection "loop" "start_s")
                        |> Expect.equal Nothing
            , test "an edit to a stem that does not exist changes nothing" <|
                \_ ->
                    config
                        |> Config.set Fixtures.schema (Config.InStem 9 "gain_db") "-6.5"
                        |> Expect.equal config
            ]
        ]
