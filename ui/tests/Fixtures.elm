module Fixtures exposing (schema, suite)

{-| A schema to build controls and configs from in tests.

Copied field-for-field out of a live `GET /api/schema`, trimmed to a
representative subset: all six `Schema.Field` kinds, both sections the mixer
consumes per stem (`stem`, `stem_decay`), two ordinary sections, and both
top-level fields. It is deliberately *not* the whole thing — a full copy would
be four hundred lines of JSON that rots the first time a parameter changes,
and nothing here is testing that the mixer can render every parameter the
server happens to have today.

The descriptions are here for the same reason the `help` strings are: the mixer
renders both, so a fixture without them would leave every test of that running
against the one case where there is nothing to render. They are shortened, but
they keep the shape the real ones have — a summary line, a blank line, and the
detail under it — because that shape is what `paragraphsOf` splits on.

`suite` exists so this module earns its place in `elm-test`'s run: it asserts
the fixture still decodes through the real decoder, so a change to `Schema.elm`
that this JSON no longer satisfies fails here rather than quietly leaving every
test that uses it running against `Dict.empty`.

-}

import Dict
import Expect
import Json.Decode as Decode
import Schema
import Test exposing (Test, describe, test)


schema : Schema.Schema
schema =
    case Decode.decodeString Schema.decoder json of
        Ok decoded ->
            decoded

        Err _ ->
            { description = "", fields = Dict.empty, sections = Dict.empty }


suite : Test
suite =
    describe "the schema fixture"
        [ test "decodes through the real decoder" <|
            \_ ->
                Decode.decodeString Schema.decoder json
                    |> Result.map (\s -> ( Dict.keys s.fields, Dict.keys s.sections ))
                    |> Expect.equal
                        (Ok
                            ( [ "seed", "separation_model" ]
                            , [ "loop", "output", "soundbed", "stem", "stem_decay", "tempo" ]
                            )
                        )
        , test "and carries a description for the config and every section" <|
            \_ ->
                (String.isEmpty schema.description
                    :: List.map (.description >> String.isEmpty) (Dict.values schema.sections)
                )
                    |> Expect.equal (List.repeat 7 False)
        ]


json : String
json =
    """
{
  "description": "Everything that decides what a finished mix sounds like.\\n\\nOne of these has a control in the mixer, under Mix: the seed, which fixes the random parts of the decay. The other belongs to the separation rather than to the mix.",
  "fields": {
    "seed": {"type": "int", "default": 0, "label": "Seed",
             "help": "Fixes the random parts of the decay.", "min": 0, "step": 1},
    "separation_model": {"type": "str", "default": "htdemucs_ft",
                         "label": "Separation model", "help": null}
  },
  "sections": {
    "loop": {"description": "Which fragment of the song gets repeated, and how the repeats are joined.\\n\\nLeave the start and end empty and a beat-aligned loop is found for you; set them and that region is used exactly.",
              "fields": {
      "bars": {"type": "int", "default": 8, "label": "Bars", "help": null,
               "min": 1, "max": 64, "step": 1},
      "beats_per_bar": {"type": "int", "default": 4, "label": "Beats per bar",
                        "help": null, "min": 1, "max": 16, "step": 1},
      "crossfade_ms": {"type": "float", "default": 120.0, "label": "Seam crossfade",
                       "help": null, "min": 0.0, "max": 2000.0, "step": 10.0,
                       "unit": "ms"},
      "search_start": {"type": "float", "default": 0.2, "label": "Search from",
                       "help": "Fraction of the track to start searching from.",
                       "min": 0.0, "max": 1.0, "step": 0.01},
      "start_s": {"type": "float", "default": null, "label": "Loop start",
                  "help": "Leave empty to auto-detect a beat-aligned loop.",
                  "min": 0.0, "unit": "s"},
      "end_s": {"type": "float", "default": null, "label": "Loop end",
                "help": "Leave empty to auto-detect a beat-aligned loop.",
                "min": 0.0, "unit": "s"}
    }},
    "tempo": {"description": "How fast and how low the loop plays, before any of it erodes.",
               "fields": {
      "speed": {"type": "float", "default": 0.7, "label": "Speed", "help": null,
                "min": 0.05, "max": 1.0, "step": 0.01, "unit": "\\u00d7"},
      "pitch_semitones": {"type": "float", "default": -2.0, "label": "Pitch",
                          "help": null, "min": -12.0, "max": 12.0, "step": 0.5,
                          "unit": "st"}
    }},
    "output": {"description": "The shape of the finished file: how long, how loud, and how it starts and ends.",
                "fields": {
      "duration_min": {"type": "float", "default": 20.0, "label": "Duration",
                       "help": null, "min": 1.0, "max": 480.0, "step": 1.0,
                       "unit": "min"},
      "sample_rate": {"type": "int", "default": 44100, "label": "Sample rate",
                      "help": null, "unit": "Hz", "choices": [22050, 44100, 48000]},
      "channels": {"type": "int", "default": 2, "label": "Channels", "help": null,
                   "choices": [1, 2]}
    }},
    "soundbed": {"description": "A continuous bed underneath the mix: noise, binaural tones, or both.\\n\\nOff by default. Mixed in when you render — previews never include it.",
                  "fields": {
      "enabled": {"type": "bool", "default": false, "label": "Sound bed", "help": null},
      "noise_type": {"type": "str", "default": "pink", "label": "Noise type",
                     "help": null, "choices": ["pink", "brown", "white", "none"]}
    }},
    "stem": {"description": "One separated stem and how it should behave in the mix.\\n\\nEvery stem the separation produced gets a row. Stems erode independently, which is the point — vocals can dissolve while the bass stays put.",
              "fields": {
      "name": {"type": "str", "default": "other", "label": "Stem", "help": null,
               "choices": ["vocals", "drums", "bass", "other", "mix"]},
      "enabled": {"type": "bool", "default": true, "label": "Enabled", "help": null},
      "gain_db": {"type": "float", "default": 0.0, "label": "Gain", "help": null,
                  "min": -24.0, "max": 12.0, "step": 0.5, "unit": "dB"},
      "reverb_send": {"type": "float", "default": 1.0, "label": "Reverb send",
                      "help": null, "min": 0.0, "max": 2.0, "step": 0.01}
    }},
    "stem_decay": {"description": "How one stem falls apart across the length of the mix.\\n\\nEvery value here has a start and an end. A mix is one loop played over and over, so the loop erodes a little more every time round.",
                    "fields": {
      "enabled": {"type": "bool", "default": true, "label": "Enabled", "help": null},
      "curve": {"type": "str", "default": "linear", "label": "Curve",
                "help": "linear \\u00b7 exp \\u00b7 log",
                "choices": ["linear", "exp", "log"]},
      "lowpass_start_hz": {"type": "float", "default": 18000.0,
                           "label": "Lowpass start", "help": null, "min": 20.0,
                           "max": 20000.0, "step": 100.0, "unit": "Hz"},
      "amp_end_db": {"type": "float", "default": -9.0, "label": "Amplitude end",
                     "help": null, "min": -60.0, "max": 0.0, "step": 0.5,
                     "unit": "dB"}
    }}
  }
}
"""
