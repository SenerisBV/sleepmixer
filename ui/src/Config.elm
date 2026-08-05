module Config exposing
    ( Config, Stem, Target(..), Value(..)
    , asBool, asFloat, encode, forPreset, fromSchema, keyOf, overlay, set, specAt, toggle, valueAt, valueString
    )

{-| The config JSON a preview — and one day a render — carries.

Nothing here knows the name of a single config parameter. The shape comes from
`/api/schema` (see `Schema.elm`), the values are held in dictionaries keyed by
whatever the server called them, and `encode` puts them back in the nesting
`MixConfig.from_dict` expects. That is the whole point: a parameter added on
the Python side appears in the mixer, is editable, and round-trips, with no
change here.

Three things are hard-coded, and only three, each because it is structural
rather than a parameter:

  - `stem` and `stem_decay` are sections describing the *elements of a list*,
    not global settings, so they are excluded from `sections` and used to build
    each stem instead.
  - a stem's `name` is what identifies the row rather than something you pick,
    so it is dropped from the editable fields and written back by `encode`.
  - `stems` itself is a list, which the schema deliberately does not describe
    (`config.py::_describe_fields` skips it).

A field whose schema default is `null` — `loop.start_s` and `loop.end_s` today
— starts absent rather than at some invented zero, and an unparseable edit
removes the key again. Absent means "the server's default", which for those two
is "detect the loop yourself"; a `0.0` would mean "start the loop at zero
seconds", which is a different instruction entirely.

-}

import Dict exposing (Dict)
import Json.Decode as Decode
import Json.Encode as Encode
import Schema


{-| A value as the API's JSON needs to carry it.

`Int` and `Float` are separate because the server's ints are genuinely ints:
`seed` reaches numpy's `SeedSequence`, which refuses a float, and
`output.sample_rate` and `output.channels` index buffers. Encoding every number
as a float would 500 somewhere deep instead of failing here.
-}
type Value
    = FloatValue Float
    | IntValue Int
    | BoolValue Bool
    | StringValue String


type alias Values =
    Dict String Value


type alias Stem =
    { name : String
    , fields : Values
    , decay : Values
    }


type alias Config =
    { top : Values
    , sections : Dict String Values
    , stems : List Stem
    }


{-| Where a value lives. Every control in the mixer carries one of these, so
the update loop has a single `set` rather than a message per parameter.
-}
type Target
    = Top String
    | InSection String String
    | InStem Int String
    | InStemDecay Int String


keyOf : Target -> String
keyOf target =
    case target of
        Top key ->
            key

        InSection _ key ->
            key

        InStem _ key ->
            key

        InStemDecay _ key ->
            key


{-| The sections that describe one stem rather than the whole mix.
-}
perStemSections : List String
perStemSections =
    [ "stem", "stem_decay" ]


{-| Every default the schema states, for the stems that actually exist.

The stem list is built from the song's separated stems rather than from
`MixConfig`'s own default list, because the schema cannot describe a list and
the stems a song has are the only ones a preview could play.

**The consequence is larger than it looks, so it is written out in full.** A
fresh mixer gives every stem `StemConfig`'s and `StemDecayConfig`'s defaults —
one identical setting for all of them. `MixConfig`'s curated list is four
different settings, and a mixer opened on a normally-separated song differs
from what `sleepmix render` would do on every one of them:

  - `drums` — enabled here, disabled there.
  - `bass` — decay enabled here, disabled there (the CLI keeps the low end
    steady on purpose).
  - `vocals` — `linear` here against `exp` there, and three endpoints the CLI
    moves: lowpass 1600 → 2200 Hz, amplitude -9 → -16 dB, spectral holes
    0.3 → 0.45.
  - `other` — lowpass 1600 → 2400 Hz, amplitude -9 → -4 dB.

So it is not "drums start on". It is that the CLI's per-stem shaping — vocals
dissolving late and far, other staying present — is absent, and every stem
erodes identically until someone moves a slider. The mixer is honest: it shows
exactly what it will render. It just does not start where the CLI starts, and
anyone comparing a mix made here against one made there should know that is
why they differ. Closing this properly needs the server to publish its default
config, not a copy of that list written out in Elm.
-}
fromSchema : Schema.Schema -> List String -> Config
fromSchema schema stemNames =
    { top = defaults schema.fields
    , sections =
        schema.sections
            |> Dict.filter (\name _ -> not (List.member name perStemSections))
            |> Dict.map (\_ aSection -> defaults aSection.fields)
    , stems = List.map (stemFor schema) stemNames
    }


stemFor : Schema.Schema -> String -> Stem
stemFor schema name =
    { name = name
    , fields = Dict.remove "name" (defaults (sectionFields "stem" schema))
    , decay = defaults (sectionFields "stem_decay" schema)
    }


sectionFields : String -> Schema.Schema -> Dict String Schema.Field
sectionFields name schema =
    Dict.get name schema.sections
        |> Maybe.map .fields
        |> Maybe.withDefault Dict.empty


defaults : Dict String Schema.Field -> Values
defaults fields =
    Dict.foldl
        (\key aField acc ->
            case defaultOf aField of
                Just value ->
                    Dict.insert key value acc

                Nothing ->
                    acc
        )
        Dict.empty
        fields


defaultOf : Schema.Field -> Maybe Value
defaultOf aField =
    case aField of
        Schema.FloatField spec ->
            Maybe.map FloatValue spec.default

        Schema.IntField spec ->
            Maybe.map (round >> IntValue) spec.default

        Schema.BoolField spec ->
            Just (BoolValue spec.default)

        Schema.TextField spec ->
            Maybe.map StringValue spec.default

        Schema.IntChoiceField spec ->
            Maybe.map IntValue spec.default

        Schema.StringChoiceField spec ->
            Maybe.map StringValue spec.default


{-| The schema entry a target points at, which is what says how to parse an
edit and what bounds to hold it to.
-}
specAt : Schema.Schema -> Target -> Maybe Schema.Field
specAt schema target =
    case target of
        Top key ->
            Dict.get key schema.fields

        InSection name key ->
            Dict.get key (sectionFields name schema)

        InStem _ key ->
            Dict.get key (sectionFields "stem" schema)

        InStemDecay _ key ->
            Dict.get key (sectionFields "stem_decay" schema)


valueAt : Target -> Config -> Maybe Value
valueAt target config =
    Dict.get (keyOf target) (valuesAt target config)


valuesAt : Target -> Config -> Values
valuesAt target config =
    case target of
        Top _ ->
            config.top

        InSection name _ ->
            Maybe.withDefault Dict.empty (Dict.get name config.sections)

        InStem index _ ->
            Maybe.withDefault Dict.empty (Maybe.map .fields (stemAt index config))

        InStemDecay index _ ->
            Maybe.withDefault Dict.empty (Maybe.map .decay (stemAt index config))


stemAt : Int -> Config -> Maybe Stem
stemAt index config =
    List.head (List.drop index config.stems)


{-| Apply an edit that arrived as a string, which is what every HTML input
gives you.

The schema does the parsing *and* the bounding: a value outside `min`/`max` is
clamped rather than sent, so the only way to reach the server with a number the
config would reject is to bypass this function. `seed` carries `min: 0` for
exactly that reason — `MixConfig.validate` raises on a negative seed, and a
control that can produce one is a control that can 400 the preview.
-}
set : Schema.Schema -> Target -> String -> Config -> Config
set schema target raw config =
    case specAt schema target of
        Nothing ->
            config

        Just aField ->
            case parse aField raw of
                Just value ->
                    alter target (Dict.insert (keyOf target) value) config

                Nothing ->
                    -- Cleared, or nonsense. Either way the key goes, and the
                    -- server's own default applies again.
                    alter target (Dict.remove (keyOf target)) config


toggle : Target -> Bool -> Config -> Config
toggle target on config =
    alter target (Dict.insert (keyOf target) (BoolValue on)) config


alter : Target -> (Values -> Values) -> Config -> Config
alter target f config =
    case target of
        Top _ ->
            { config | top = f config.top }

        InSection name _ ->
            { config | sections = Dict.update name (Maybe.map f) config.sections }

        InStem index _ ->
            { config | stems = updateStem index (\s -> { s | fields = f s.fields }) config.stems }

        InStemDecay index _ ->
            { config | stems = updateStem index (\s -> { s | decay = f s.decay }) config.stems }


updateStem : Int -> (Stem -> Stem) -> List Stem -> List Stem
updateStem index f =
    List.indexedMap
        (\i stem ->
            if i == index then
                f stem

            else
                stem
        )


parse : Schema.Field -> String -> Maybe Value
parse aField raw =
    let
        trimmed =
            String.trim raw
    in
    case aField of
        Schema.FloatField spec ->
            String.toFloat trimmed
                |> Maybe.map (clampTo spec.min spec.max >> FloatValue)

        Schema.IntField spec ->
            String.toFloat trimmed
                |> Maybe.map (clampTo spec.min spec.max >> round >> IntValue)

        Schema.BoolField _ ->
            case String.toLower trimmed of
                "true" ->
                    Just (BoolValue True)

                "false" ->
                    Just (BoolValue False)

                _ ->
                    Nothing

        Schema.TextField _ ->
            -- Emptied means "whatever the server had", not the empty string.
            -- `separation_model` is the field this is about: `""` reaches
            -- Demucs as a model name and fails there rather than here.
            if String.isEmpty trimmed then
                Nothing

            else
                Just (StringValue raw)

        Schema.IntChoiceField spec ->
            String.toInt trimmed
                |> Maybe.andThen (memberOf spec.choices)
                |> Maybe.map IntValue

        Schema.StringChoiceField spec ->
            Maybe.map StringValue (memberOf spec.choices trimmed)


{-| A choice the schema does not offer is refused rather than passed through: a
`<select>` cannot produce one, so anything else arriving here is a bug and
silently forwarding it would push the failure into the DSP.
-}
memberOf : List a -> a -> Maybe a
memberOf choices candidate =
    if List.member candidate choices then
        Just candidate

    else
        Nothing


clampTo : Maybe Float -> Maybe Float -> Float -> Float
clampTo low high value =
    let
        floored =
            case low of
                Just lo ->
                    Basics.max lo value

                Nothing ->
                    value
    in
    case high of
        Just hi ->
            Basics.min hi floored

        Nothing ->
            floored


{-| Take a config as JSON — a preset, or the server's own defaults — and lay it
over a base config.

Every key the JSON carries *and the schema describes* replaces the base's —
inserting it if the base did not already have it, not merely overwriting a key
that was there. That distinction matters because `fromSchema` leaves a field
absent whenever the schema's own default is `null` (`loop.start_s` and
`loop.end_s`, today): the base genuinely has no key for them, so a `Dict.map`
over the base's existing keys could never introduce one, and a preset or a
server default carrying a concrete value for one of those fields would land
silently as a no-op. The schema, not the base's current shape, is what decides
which keys may exist; the base only decides what they hold when the JSON is
silent.

Every key the JSON does not carry keeps the base's value untouched. Callers
always pass `fromSchema`'s output as the base, so "a field this preset does
not mention" means "that field's default" rather than "whatever happened to be
on screen". Apply means *make it look like this*, not *merge this in*: a
preset saved before a field existed would otherwise leave that field holding a
value from a recipe the operator believes they replaced, with nothing on
screen saying which control came from where.

A key the schema does not describe is ignored regardless of which side has
it, which is what lets a preset written by an older or newer build load rather
than fail.

Values go through `parse`, the same function every typed control uses, so the
schema's bounds and choice lists are enforced in exactly one place. A preset
saved before a bound was tightened shows a value the mixer will accept, not one
the server rejects minutes later at render time.
-}
overlay : Schema.Schema -> Decode.Value -> Config -> Config
overlay schema raw base =
    let
        incoming =
            objectOf raw

        incomingStems =
            Dict.get "stems" incoming
                |> Maybe.map stemsByName
                |> Maybe.withDefault Dict.empty
    in
    { top = overlayValues schema Top incoming base.top
    , sections =
        Dict.map
            (\name values ->
                overlayValues schema
                    (InSection name)
                    (Dict.get name incoming |> Maybe.map objectOf |> Maybe.withDefault Dict.empty)
                    values
            )
            base.sections
    , stems = List.indexedMap (overlayStem schema incomingStems) base.stems
    }


objectOf : Decode.Value -> Dict String Decode.Value
objectOf raw =
    Decode.decodeValue (Decode.dict Decode.value) raw
        |> Result.withDefault Dict.empty


stemsByName : Decode.Value -> Dict String (Dict String Decode.Value)
stemsByName raw =
    Decode.decodeValue (Decode.list (Decode.dict Decode.value)) raw
        |> Result.withDefault []
        |> List.filterMap
            (\entry ->
                Dict.get "name" entry
                    |> Maybe.andThen (Decode.decodeValue Decode.string >> Result.toMaybe)
                    |> Maybe.map (\name -> ( name, entry ))
            )
        |> Dict.fromList


overlayStem : Schema.Schema -> Dict String (Dict String Decode.Value) -> Int -> Stem -> Stem
overlayStem schema incoming index stem =
    case Dict.get stem.name incoming of
        Nothing ->
            stem

        Just entry ->
            { stem
                | fields =
                    -- `name` identifies the stem rather than being something
                    -- you pick, so it is stripped before overlaying — the
                    -- same reason `stemFor` never puts it in `fields` to begin
                    -- with. Left in, the schema-authority insert below would
                    -- happily add it back, and `encode` would then write
                    -- `name` twice.
                    overlayValues schema (InStem index) (Dict.remove "name" entry) stem.fields
                , decay =
                    overlayValues schema
                        (InStemDecay index)
                        (Dict.get "decay" entry |> Maybe.map objectOf |> Maybe.withDefault Dict.empty)
                        stem.decay
            }


overlayValues : Schema.Schema -> (String -> Target) -> Dict String Decode.Value -> Values -> Values
overlayValues schema toTarget incoming existing =
    -- Folding over `incoming` rather than mapping over `existing` is the
    -- whole fix: `existing` can lack a key entirely (a `null`-default field
    -- is absent from `fromSchema`'s output, not present-and-empty), and a
    -- `Dict.map` can only ever change a value already there, never introduce
    -- one. The schema is the authority on which keys may land — a key it
    -- does not describe is skipped whether or not `existing` already has it,
    -- which keeps a key the schema does not describe from being carried.
    Dict.foldl
        (\key rawValue acc ->
            case specAt schema (toTarget key) of
                Nothing ->
                    acc

                Just spec ->
                    case fromJson spec rawValue of
                        Just value ->
                            Dict.insert key value acc

                        Nothing ->
                            acc
        )
        existing
        incoming


{-| One JSON value, through the schema's own parser.
-}
fromJson : Schema.Field -> Decode.Value -> Maybe Value
fromJson spec raw =
    let
        text decoder =
            Decode.decodeValue decoder raw |> Result.toMaybe
    in
    (case spec of
        Schema.FloatField _ ->
            Maybe.map String.fromFloat (text Decode.float)

        Schema.IntField _ ->
            Maybe.map String.fromInt (text Decode.int)

        Schema.BoolField _ ->
            Maybe.map
                (\b ->
                    if b then
                        "true"

                    else
                        "false"
                )
                (text Decode.bool)

        Schema.TextField _ ->
            text Decode.string

        Schema.IntChoiceField _ ->
            Maybe.map String.fromInt (text Decode.int)

        Schema.StringChoiceField _ ->
            text Decode.string
    )
        |> Maybe.andThen (parse spec)


{-| The config as a preset should store it.

Two things are removed, and both are silent when they are wrong.

`loop.start_s` and `loop.end_s` are seconds into one particular song. Carried
into a preset they would move another song's loop region to a place chosen for
different audio, and nothing on screen would say why the mix changed.

`separation_model` is not a mix setting at all: changing it nulls the session's
stems, so the next preview runs a real Demucs separation inside the per-song
preview lock — minutes, no progress reporting, on a screen that already
believes itself playable. `Page.Mixer` withholds a control for it by name for
exactly that reason; a preset must not smuggle one in.
-}
forPreset : Config -> Encode.Value
forPreset config =
    encode
        { config
            | top = Dict.remove "separation_model" config.top
            , sections =
                Dict.update "loop"
                    (Maybe.map (Dict.remove "start_s" >> Dict.remove "end_s"))
                    config.sections
        }


{-| What an `<input>`'s `value` attribute should read.
-}
valueString : Value -> String
valueString value =
    case value of
        FloatValue f ->
            String.fromFloat f

        IntValue i ->
            String.fromInt i

        BoolValue True ->
            "true"

        BoolValue False ->
            "false"

        StringValue s ->
            s


asBool : Value -> Maybe Bool
asBool value =
    case value of
        BoolValue b ->
            Just b

        _ ->
            Nothing


{-| A number, whichever of the two number shapes it is being held as.
-}
asFloat : Value -> Maybe Float
asFloat value =
    case value of
        FloatValue f ->
            Just f

        IntValue i ->
            Just (toFloat i)

        _ ->
            Nothing


encode : Config -> Encode.Value
encode config =
    Encode.object
        (List.concat
            [ pairs config.top
            , List.map
                (\( name, values ) -> ( name, Encode.object (pairs values) ))
                (Dict.toList config.sections)
            , [ ( "stems", Encode.list encodeStem config.stems ) ]
            ]
        )


encodeStem : Stem -> Encode.Value
encodeStem stem =
    Encode.object
        (( "name", Encode.string stem.name )
            :: pairs stem.fields
            ++ [ ( "decay", Encode.object (pairs stem.decay) ) ]
        )


pairs : Values -> List ( String, Encode.Value )
pairs values =
    List.map (\( key, value ) -> ( key, encodeValue value )) (Dict.toList values)


encodeValue : Value -> Encode.Value
encodeValue value =
    case value of
        FloatValue f ->
            Encode.float f

        IntValue i ->
            Encode.int i

        BoolValue b ->
            Encode.bool b

        StringValue s ->
            Encode.string s
