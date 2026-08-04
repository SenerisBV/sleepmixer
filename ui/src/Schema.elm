module Schema exposing (Field(..), Schema, Section, decoder, fieldLabel)

{-| The server's own description of its config, decoded into something the
compiler can check.

Controls are generated from this rather than hand-written, so a new config
parameter appears in the interface without a frontend change. The union is
closed on purpose: a field type this application cannot render fails the
decode loudly instead of rendering nothing. That is most of the reason the
project chose Elm.
-}

import Dict exposing (Dict)
import Json.Decode as Decode exposing (Decoder)


type alias NumberSpec =
    { label : String
    , help : Maybe String
    , default : Maybe Float
    , min : Maybe Float
    , max : Maybe Float
    , step : Maybe Float
    , unit : Maybe String
    }


type alias BoolSpec =
    { label : String, help : Maybe String, default : Bool }


type alias TextSpec =
    { label : String, help : Maybe String, default : Maybe String }


type alias ChoiceSpec a =
    { label : String, help : Maybe String, default : Maybe a, choices : List a }


type Field
    = FloatField NumberSpec
    | IntField NumberSpec
    | BoolField BoolSpec
    | TextField TextSpec
    | IntChoiceField (ChoiceSpec Int)
    | StringChoiceField (ChoiceSpec String)


type alias Section =
    { fields : Dict String Field }


type alias Schema =
    { fields : Dict String Field, sections : Dict String Section }


fieldLabel : Field -> String
fieldLabel aField =
    case aField of
        FloatField spec ->
            spec.label

        IntField spec ->
            spec.label

        BoolField spec ->
            spec.label

        TextField spec ->
            spec.label

        IntChoiceField spec ->
            spec.label

        StringChoiceField spec ->
            spec.label


decoder : Decoder Schema
decoder =
    Decode.map2 Schema
        (Decode.field "fields" (Decode.dict field))
        (Decode.field "sections" (Decode.dict section))


section : Decoder Section
section =
    Decode.map Section (Decode.field "fields" (Decode.dict field))


{-| Dispatch on the type *and* on whether choices are present: the server emits
`int` and `str` both with and without them, and a select and a slider are not
interchangeable.
-}
field : Decoder Field
field =
    Decode.map2 Tuple.pair
        (Decode.field "type" Decode.string)
        (Decode.maybe (Decode.field "choices" Decode.value))
        |> Decode.andThen
            (\( kind, choices ) ->
                case ( kind, choices ) of
                    ( "float", _ ) ->
                        Decode.map FloatField numberSpec

                    ( "int", Nothing ) ->
                        Decode.map IntField numberSpec

                    ( "int", Just _ ) ->
                        Decode.map IntChoiceField (choiceSpec Decode.int)

                    ( "bool", _ ) ->
                        Decode.map BoolField boolSpec

                    ( "str", Nothing ) ->
                        Decode.map TextField textSpec

                    ( "str", Just _ ) ->
                        Decode.map StringChoiceField (choiceSpec Decode.string)

                    ( other, _ ) ->
                        Decode.fail ("unknown config field type: " ++ other)
            )


numberSpec : Decoder NumberSpec
numberSpec =
    Decode.map7 NumberSpec
        (Decode.field "label" Decode.string)
        (Decode.field "help" (Decode.nullable Decode.string))
        (Decode.field "default" (Decode.nullable Decode.float))
        (Decode.maybe (Decode.field "min" Decode.float))
        (Decode.maybe (Decode.field "max" Decode.float))
        (Decode.maybe (Decode.field "step" Decode.float))
        (Decode.maybe (Decode.field "unit" Decode.string))


boolSpec : Decoder BoolSpec
boolSpec =
    Decode.map3 BoolSpec
        (Decode.field "label" Decode.string)
        (Decode.field "help" (Decode.nullable Decode.string))
        (Decode.field "default" Decode.bool)


textSpec : Decoder TextSpec
textSpec =
    Decode.map3 TextSpec
        (Decode.field "label" Decode.string)
        (Decode.field "help" (Decode.nullable Decode.string))
        (Decode.field "default" (Decode.nullable Decode.string))


choiceSpec : Decoder a -> Decoder (ChoiceSpec a)
choiceSpec value =
    Decode.map4 ChoiceSpec
        (Decode.field "label" Decode.string)
        (Decode.field "help" (Decode.nullable Decode.string))
        (Decode.field "default" (Decode.nullable value))
        (Decode.field "choices" (Decode.list value))
