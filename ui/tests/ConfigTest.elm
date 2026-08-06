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
import Json.Encode as Encode
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
                            [ "bars", "beats_per_bar", "crossfade_ms", "search_start" ]
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
        , describe "the fields that are not numbers"
            -- Every other `Config.set` in this file is numeric or deliberately
            -- invalid, so until these existed *no* test set a valid value on a
            -- `StringChoiceField`, an `IntChoiceField` or a `TextField`.
            -- Inverting `memberOf`, or making `parse` return `Nothing` for a
            -- choice field, left the suite green while every `<select>` in the
            -- mixer silently deleted its key: pick `exp` and the control snaps
            -- back to `linear`, which is also the default, so nothing appears
            -- to have happened — and the render uses `linear`.
            [ test "a curve the schema does offer is kept" <|
                \_ ->
                    config
                        |> Config.set Fixtures.schema (Config.InStemDecay 0 "curve") "exp"
                        |> expect
                            (stemField 0 "decay" (Decode.field "curve" Decode.string))
                            "exp"
            , test "so is a choice from a different string select" <|
                \_ ->
                    config
                        |> Config.set Fixtures.schema (Config.InSection "soundbed" "noise_type") "brown"
                        |> expect (Decode.at [ "soundbed", "noise_type" ] Decode.string) "brown"
            , test "an integer choice is kept, and stays an integer" <|
                \_ ->
                    -- `output.sample_rate` and `output.channels` index buffers
                    -- on the server; a float there fails deep rather than here.
                    config
                        |> Config.set Fixtures.schema (Config.InSection "output" "sample_rate") "22050"
                        |> expect (Decode.at [ "output", "sample_rate" ] Decode.int) 22050
            , test "an integer choice the schema does not offer is refused" <|
                \_ ->
                    config
                        |> Config.set Fixtures.schema (Config.InSection "output" "sample_rate") "96000"
                        |> expect (Decode.field "output" keysOf) [ "channels", "duration_min" ]
            , test "a text field keeps what was typed into it" <|
                \_ ->
                    config
                        |> Config.set Fixtures.schema (Config.Top "separation_model") "htdemucs"
                        |> expect (Decode.field "separation_model" Decode.string) "htdemucs"
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
                            [ "bars", "beats_per_bar", "crossfade_ms", "search_start" ]
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
        , overlaySuite
        , forPresetSuite
        , domIdSuite
        ]


overlaySuite : Test
overlaySuite =
    describe "Config.overlay"
        [ test "a value the JSON carries replaces the default" <|
            \_ ->
                Config.fromSchema Fixtures.schema [ "vocals" ]
                    |> Config.overlay Fixtures.schema (json """{"seed": 7}""")
                    |> Config.valueAt (Config.Top "seed")
                    |> Expect.equal (Just (Config.IntValue 7))
        , test "a value lands even where the base has no key to overwrite" <|
            \_ ->
                -- `loop.start_s`'s schema default is `null`, so `fromSchema`
                -- never gives the base a key for it at all — there is nothing
                -- for a `Dict.map` over the base to replace. The schema, not
                -- the base's current shape, has to be what decides this key
                -- may exist.
                Config.fromSchema Fixtures.schema [ "vocals" ]
                    |> Config.overlay Fixtures.schema (json """{"loop": {"start_s": 12.5}}""")
                    |> Config.valueAt (Config.InSection "loop" "start_s")
                    |> Expect.equal (Just (Config.FloatValue 12.5))
        , test "a value the JSON omits keeps the base's" <|
            \_ ->
                Config.fromSchema Fixtures.schema [ "vocals" ]
                    |> Config.overlay Fixtures.schema (json """{"seed": 7}""")
                    |> Config.valueAt (Config.InSection "tempo" "speed")
                    |> Expect.equal
                        (Config.valueAt (Config.InSection "tempo" "speed")
                            (Config.fromSchema Fixtures.schema [ "vocals" ])
                        )
        , test "a key the schema does not describe is ignored, not carried" <|
            \_ ->
                Config.fromSchema Fixtures.schema [ "vocals" ]
                    |> Config.overlay Fixtures.schema (json """{"invented_field": 1}""")
                    |> Config.valueAt (Config.Top "invented_field")
                    |> Expect.equal Nothing
        , test "a value outside the schema's bounds is clamped, not taken" <|
            \_ ->
                Config.fromSchema Fixtures.schema [ "vocals" ]
                    |> Config.overlay Fixtures.schema (json """{"tempo": {"speed": 99.0}}""")
                    |> Config.valueAt (Config.InSection "tempo" "speed")
                    |> Expect.equal (Just (Config.FloatValue 1.0))
        , test "a stem is matched by name, not by position" <|
            \_ ->
                Config.fromSchema Fixtures.schema [ "drums", "vocals" ]
                    |> Config.overlay Fixtures.schema
                        (json """{"stems": [{"name": "vocals", "gain_db": -6.0}]}""")
                    |> Config.valueAt (Config.InStem 1 "gain_db")
                    |> Expect.equal (Just (Config.FloatValue -6.0))
        , test "a stem the JSON does not mention keeps its defaults" <|
            \_ ->
                Config.fromSchema Fixtures.schema [ "drums", "vocals" ]
                    |> Config.overlay Fixtures.schema
                        (json """{"stems": [{"name": "vocals", "gain_db": -6.0}]}""")
                    |> Config.valueAt (Config.InStem 0 "gain_db")
                    |> Expect.equal
                        (Config.valueAt (Config.InStem 0 "gain_db")
                            (Config.fromSchema Fixtures.schema [ "drums", "vocals" ])
                        )
        , test "a stem the song does not have is not invented" <|
            \_ ->
                Config.fromSchema Fixtures.schema [ "vocals" ]
                    |> Config.overlay Fixtures.schema
                        (json """{"stems": [{"name": "tuba", "gain_db": -6.0}]}""")
                    |> .stems
                    |> List.map .name
                    |> Expect.equal [ "vocals" ]
        , test "per-stem decay is overlaid too" <|
            \_ ->
                Config.fromSchema Fixtures.schema [ "vocals" ]
                    |> Config.overlay Fixtures.schema
                        (json """{"stems": [{"name": "vocals", "decay": {"curve": "exp"}}]}""")
                    |> Config.valueAt (Config.InStemDecay 0 "curve")
                    |> Expect.equal (Just (Config.StringValue "exp"))
        ]


forPresetSuite : Test
forPresetSuite =
    describe "Config.forPreset"
        [ test "the loop region a song is set to does not travel" <|
            \_ ->
                Config.fromSchema Fixtures.schema [ "vocals" ]
                    |> Config.set Fixtures.schema (Config.InSection "loop" "start_s") "12.5"
                    |> Config.forPreset
                    |> Encode.encode 0
                    |> String.contains "start_s"
                    |> Expect.equal False
        , test "nor the end of it" <|
            \_ ->
                Config.fromSchema Fixtures.schema [ "vocals" ]
                    |> Config.set Fixtures.schema (Config.InSection "loop" "end_s") "30.0"
                    |> Config.forPreset
                    |> Encode.encode 0
                    |> String.contains "end_s"
                    |> Expect.equal False
        , test "the portable half of the loop section does travel" <|
            \_ ->
                Config.fromSchema Fixtures.schema [ "vocals" ]
                    |> Config.forPreset
                    |> Encode.encode 0
                    |> String.contains "beats_per_bar"
                    |> Expect.equal True
        , test "the separation model does not travel" <|
            \_ ->
                Config.fromSchema Fixtures.schema [ "vocals" ]
                    |> Config.forPreset
                    |> Encode.encode 0
                    |> String.contains "separation_model"
                    |> Expect.equal False
        , test "everything else still does" <|
            \_ ->
                Config.fromSchema Fixtures.schema [ "vocals" ]
                    |> Config.forPreset
                    |> Encode.encode 0
                    |> String.contains "gain_db"
                    |> Expect.equal True
        , test "the seed travels, so a preset reproduces the same erosion" <|
            \_ ->
                Config.fromSchema Fixtures.schema [ "vocals" ]
                    |> Config.set Fixtures.schema (Config.Top "seed") "42"
                    |> Config.forPreset
                    |> Encode.encode 0
                    |> String.contains "42"
                    |> Expect.equal True
        ]


json : String -> Decode.Value
json raw =
    Decode.decodeString Decode.value raw
        |> Result.withDefault Encode.null


domIdSuite : Test
domIdSuite =
    describe "Config.domId"
        [ test "two stems' identically-named fields do not collide" <|
            \_ ->
                Expect.notEqual
                    (Config.domId (Config.InStem 0 "enabled"))
                    (Config.domId (Config.InStem 1 "enabled"))
        , test "a stem field and its decay counterpart do not collide" <|
            \_ ->
                Expect.notEqual
                    (Config.domId (Config.InStem 0 "enabled"))
                    (Config.domId (Config.InStemDecay 0 "enabled"))
        , test "the same field in two sections does not collide" <|
            \_ ->
                Expect.notEqual
                    (Config.domId (Config.InSection "loop" "bars"))
                    (Config.domId (Config.InSection "output" "bars"))
        , test "a top-level field does not collide with a section's" <|
            \_ ->
                Expect.notEqual
                    (Config.domId (Config.Top "seed"))
                    (Config.domId (Config.InSection "loop" "seed"))
        , test "it is stable for the same target" <|
            \_ ->
                Expect.equal
                    (Config.domId (Config.InStem 2 "gain_db"))
                    (Config.domId (Config.InStem 2 "gain_db"))
        ]
