module SchemaTest exposing (suite)

import Dict
import Json.Decode as Decode
import Expect
import Schema
import Test exposing (Test, describe, test)


{-| Verbatim fragments of the server's real `GET /api/schema` output (task-5
brief, and reconfirmed against a running instance). Each is wrapped in a
minimal object so it can be decoded on its own with `Schema.decoder`'s inner
`field` decoder via a one-entry `fields` dict.
-}
speedJson : String
speedJson =
    """
    { "type":"float","default":0.7,"label":"Speed"
    , "help":"Playback speed as a fraction of the original. 0.7 = 70% speed."
    , "min":0.05,"max":1.0,"step":0.01,"unit":"×" }
    """


sampleRateJson : String
sampleRateJson =
    """
    { "type":"int","default":44100,"label":"Sample rate","help":null
    , "unit":"Hz","choices":[22050,44100,48000] }
    """


enabledJson : String
enabledJson =
    """
    { "type":"bool","default":true,"label":"Enabled","help":null }
    """


curveJson : String
curveJson =
    """
    { "type":"str","default":"linear","label":"Curve","help":"linear · exp …"
    , "choices":["linear","exp","log"] }
    """


startSJson : String
startSJson =
    """
    { "type":"float","default":null,"label":"Loop start"
    , "help":"Leave empty to auto-detect a beat-aligned loop."
    , "min":0.0,"unit":"s" }
    """


separationModelJson : String
separationModelJson =
    """
    { "type":"str","default":"htdemucs_ft","label":"Separation model","help":null }
    """


seedJson : String
seedJson =
    """
    { "type":"int","default":0,"label":"Seed","help":null }
    """


{-| A whole `/api/schema` response with one section (`loop`), whose fields are
its real shape, `start_s` and all — exercises `Section`'s decoder, which isn't
exposed on its own. The section's `description` is the real captured value
(task-3, `SLEEPMIX_DATA_DIR=$(mktemp -d) pipenv run sleepmix ui --no-open
--port 8765`, `curl -s localhost:8765/api/schema`). -}
schemaWithLoopSectionJson : String
schemaWithLoopSectionJson =
    """
    { "fields": {}
    , "sections":
        { "loop":
            { "description":"Which fragment of the song gets repeated, and how the repeats are joined.\\n\\nA mix is one loop played over and over for however long you asked for.\\nLeave the start and end empty and a beat-aligned loop is found for you,\\nsomewhere between the search bounds; set them and that region is used\\nexactly. Everything here is about choosing and joining the fragment — the\\neroding happens elsewhere."
            , "fields":
                { "start_s":
                    { "type":"float","default":null,"label":"Loop start"
                    , "help":"Leave empty to auto-detect a beat-aligned loop."
                    , "min":0.0,"unit":"s" }
                , "bars":
                    { "type":"int","default":8,"label":"Bars","help":null
                    , "min":1,"max":64,"step":1 }
                }
            }
        }
    }
    """


{-| A full `/api/schema` response shape: top-level `fields` plus one
`sections` entry, enough to exercise `Schema.decoder` end to end. The
top-level `description` is the real captured value, from the same server
run as `schemaWithLoopSectionJson`. -}
wholeSchemaJson : String
wholeSchemaJson =
    """
    { "description":"Everything that decides what a finished mix sounds like.\\n\\nThe mixer groups these two under \\"Mix\\": a seed that fixes the random parts\\nof the decay so the same settings give the same mix twice, and the name of\\nthe model used to split the song into stems."
    , "fields":
        { "seed": { "type":"int","default":0,"label":"Seed","help":null }
        , "separation_model":
            { "type":"str","default":"htdemucs_ft","label":"Separation model","help":null }
        }
    , "sections":
        { "loop":
            { "fields":
                { "start_s":
                    { "type":"float","default":null,"label":"Loop start"
                    , "help":"Leave empty to auto-detect a beat-aligned loop."
                    , "min":0.0,"unit":"s" }
                , "sample_rate":
                    { "type":"int","default":44100,"label":"Sample rate","help":null
                    , "unit":"Hz","choices":[22050,44100,48000] }
                }
            }
        }
    }
    """


{-| A section with no `description` key at all — the shape an older server
(or a hand-built fixture) might send. Decoding this must not fail; it should
land on `""` per the brief, since a missing paragraph is a smaller failure
than a mixer that will not load. -}
sectionMissingDescriptionJson : String
sectionMissingDescriptionJson =
    """
    { "fields":
        { "seed": { "type":"int","default":0,"label":"Seed","help":null } }
    }
    """


unknownTypeJson : String
unknownTypeJson =
    """
    { "type":"teleport","default":null,"label":"Nope","help":null }
    """


{-| The server never actually omits `default` — every real fragment sends it,
`null` or otherwise. But that's exactly why this fixture is worth having:
`Decode.nullable` and `Decode.maybe (Decode.field ...)` agree on every
fixture that has the key (both land on `Nothing` for `"default": null`,
since `Decode.float` fails on `null` either way) and only diverge when the
key is missing outright. Without this case, swapping `numberSpec`'s
`default` decoder from `nullable` to `maybe (field ...)` is invisible to the
suite — it silently yields `Nothing` instead of failing. This fixture pins
that the key is required, which is the whole point of using `nullable`
there instead of `maybe`. -}
missingDefaultJson : String
missingDefaultJson =
    """
    { "type":"float","label":"No default key","help":null,"min":0.0 }
    """


{-| Decode a lone field-object fragment the way `Schema.decoder` would meet it:
nested one level under a `fields` dict, since `field` itself isn't exposed. -}
decodeField : String -> Result Decode.Error Schema.Field
decodeField json =
    let
        wrapped =
            "{ \"fields\": { \"x\": " ++ json ++ " }, \"sections\": {} }"
    in
    Decode.decodeString Schema.decoder wrapped
        |> Result.andThen
            (\schema ->
                case Dict.get "x" schema.fields of
                    Just f ->
                        Ok f

                    Nothing ->
                        Decode.decodeString (Decode.fail "missing field 'x'") "null"
            )


{-| Decode a lone section-object fragment the way `Schema.decoder` would meet
it: nested under a `sections` dict, since `section` itself isn't exposed. -}
decodeSection : String -> Result Decode.Error Schema.Section
decodeSection json =
    let
        wrapped =
            "{ \"fields\": {}, \"sections\": { \"x\": " ++ json ++ " } }"
    in
    Decode.decodeString Schema.decoder wrapped
        |> Result.andThen
            (\schema ->
                case Dict.get "x" schema.sections of
                    Just s ->
                        Ok s

                    Nothing ->
                        Decode.decodeString (Decode.fail "missing section 'x'") "null"
            )


suite : Test
suite =
    describe "Schema"
        [ describe "the six (type, has-choices) combinations"
            [ test "float with no choices decodes to FloatField" <|
                \_ ->
                    case decodeField speedJson of
                        Ok (Schema.FloatField spec) ->
                            Expect.all
                                [ .label >> Expect.equal "Speed"
                                , .default >> Expect.equal (Just 0.7)
                                , .min >> Expect.equal (Just 0.05)
                                , .max >> Expect.equal (Just 1.0)
                                , .step >> Expect.equal (Just 0.01)
                                , .unit >> Expect.equal (Just "×")
                                ]
                                spec

                        Ok other ->
                            Expect.fail ("expected FloatField, got " ++ describeField other)

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            , test "int with no choices decodes to IntField" <|
                \_ ->
                    case decodeField seedJson of
                        Ok (Schema.IntField spec) ->
                            Expect.all
                                [ .label >> Expect.equal "Seed"
                                , .default >> Expect.equal (Just 0)
                                , .min >> Expect.equal Nothing
                                , .max >> Expect.equal Nothing
                                , .unit >> Expect.equal Nothing
                                ]
                                spec

                        Ok other ->
                            Expect.fail ("expected IntField, got " ++ describeField other)

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            , test "int with choices decodes to IntChoiceField" <|
                \_ ->
                    case decodeField sampleRateJson of
                        Ok (Schema.IntChoiceField spec) ->
                            Expect.all
                                [ .label >> Expect.equal "Sample rate"
                                , .default >> Expect.equal (Just 44100)
                                , .choices >> Expect.equal [ 22050, 44100, 48000 ]
                                ]
                                spec

                        Ok other ->
                            Expect.fail ("expected IntChoiceField, got " ++ describeField other)

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            , test "bool decodes to BoolField" <|
                \_ ->
                    case decodeField enabledJson of
                        Ok (Schema.BoolField spec) ->
                            Expect.all
                                [ .label >> Expect.equal "Enabled"
                                , .default >> Expect.equal True
                                ]
                                spec

                        Ok other ->
                            Expect.fail ("expected BoolField, got " ++ describeField other)

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            , test "str with no choices decodes to TextField" <|
                \_ ->
                    case decodeField separationModelJson of
                        Ok (Schema.TextField spec) ->
                            Expect.all
                                [ .label >> Expect.equal "Separation model"
                                , .default >> Expect.equal (Just "htdemucs_ft")
                                ]
                                spec

                        Ok other ->
                            Expect.fail ("expected TextField, got " ++ describeField other)

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            , test "str with choices decodes to StringChoiceField" <|
                \_ ->
                    case decodeField curveJson of
                        Ok (Schema.StringChoiceField spec) ->
                            Expect.all
                                [ .label >> Expect.equal "Curve"
                                , .default >> Expect.equal (Just "linear")
                                , .choices >> Expect.equal [ "linear", "exp", "log" ]
                                ]
                                spec

                        Ok other ->
                            Expect.fail ("expected StringChoiceField, got " ++ describeField other)

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            ]
        , describe "optional keys"
            [ test "start_s decodes with a Nothing default and no max" <|
                \_ ->
                    case decodeField startSJson of
                        Ok (Schema.FloatField spec) ->
                            Expect.all
                                [ .default >> Expect.equal Nothing
                                , .min >> Expect.equal (Just 0.0)
                                , .max >> Expect.equal Nothing
                                , .step >> Expect.equal Nothing
                                , .unit >> Expect.equal (Just "s")
                                ]
                                spec

                        Ok other ->
                            Expect.fail ("expected FloatField, got " ++ describeField other)

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            ]
        , describe "closed union"
            [ test "an unrecognised field type fails the decode rather than being dropped" <|
                \_ ->
                    decodeField unknownTypeJson
                        |> Expect.err
            ]
        , describe "default is required, even though the server always sends it"
            [ test "a field with the default key omitted fails the decode" <|
                \_ ->
                    decodeField missingDefaultJson
                        |> Expect.err
            ]
        , describe "sections and whole responses"
            [ test "a section round-trips within a whole response, start_s and all" <|
                \_ ->
                    case Decode.decodeString Schema.decoder schemaWithLoopSectionJson of
                        Ok schema ->
                            case Dict.get "loop" schema.sections of
                                Just loopSection ->
                                    Expect.all
                                        [ \fields ->
                                            Dict.get "start_s" fields
                                                |> Maybe.map Schema.fieldLabel
                                                |> Expect.equal (Just "Loop start")
                                        , \fields ->
                                            Dict.get "bars" fields
                                                |> Maybe.map Schema.fieldLabel
                                                |> Expect.equal (Just "Bars")
                                        , \_ ->
                                            loopSection.description
                                                |> Expect.equal "Which fragment of the song gets repeated, and how the repeats are joined.\n\nA mix is one loop played over and over for however long you asked for.\nLeave the start and end empty and a beat-aligned loop is found for you,\nsomewhere between the search bounds; set them and that region is used\nexactly. Everything here is about choosing and joining the fragment — the\neroding happens elsewhere."
                                        ]
                                        loopSection.fields

                                Nothing ->
                                    Expect.fail "expected a 'loop' section"

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            , test "a whole /api/schema response decodes: top-level fields and a nested section" <|
                \_ ->
                    case Decode.decodeString Schema.decoder wholeSchemaJson of
                        Ok schema ->
                            Expect.all
                                [ \s -> Dict.get "seed" s.fields |> Maybe.map Schema.fieldLabel |> Expect.equal (Just "Seed")
                                , \s -> Dict.get "separation_model" s.fields |> Maybe.map Schema.fieldLabel |> Expect.equal (Just "Separation model")
                                , \s ->
                                    Dict.get "loop" s.sections
                                        |> Maybe.andThen (\sec -> Dict.get "start_s" sec.fields)
                                        |> Maybe.map Schema.fieldLabel
                                        |> Expect.equal (Just "Loop start")
                                , \s ->
                                    Dict.get "loop" s.sections
                                        |> Maybe.andThen (\sec -> Dict.get "sample_rate" sec.fields)
                                        |> Maybe.map Schema.fieldLabel
                                        |> Expect.equal (Just "Sample rate")
                                , \s ->
                                    s.description
                                        |> Expect.equal "Everything that decides what a finished mix sounds like.\n\nThe mixer groups these two under \"Mix\": a seed that fixes the random parts\nof the decay so the same settings give the same mix twice, and the name of\nthe model used to split the song into stems."
                                ]
                                schema

                        Err err ->
                            Expect.fail (Decode.errorToString err)
            ]
        , describe "descriptions"
            [ test "a section without a description decodes to \"\" rather than failing" <|
                \_ ->
                    decodeSection sectionMissingDescriptionJson
                        |> Result.map .description
                        |> Expect.equal (Ok "")
            ]
        ]


describeField : Schema.Field -> String
describeField field =
    case field of
        Schema.FloatField _ ->
            "FloatField"

        Schema.IntField _ ->
            "IntField"

        Schema.BoolField _ ->
            "BoolField"

        Schema.TextField _ ->
            "TextField"

        Schema.IntChoiceField _ ->
            "IntChoiceField"

        Schema.StringChoiceField _ ->
            "StringChoiceField"
