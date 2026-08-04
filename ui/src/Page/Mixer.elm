module Page.Mixer exposing
    ( State
    , everyStemDisabled, init, loopOverride, params, setField, setProgress, soloedStems, toggleField, toggleSolo
    , view
    )

{-| The mixer: hear one point in the decay arc while you shape it.

Everything on this screen except the scrubber and the solo buttons is generated
from `/api/schema`. Not for elegance — because a hand-written control panel
drifts from the config the moment a parameter is added on the Python side, and
the drift is silent: the slider is simply missing, and the value it would have
set stays at a default nobody chose. The rule for what a field becomes is the
schema's own metadata: `min`/`max`/`step` makes a slider, `choices` makes a
select, a bool makes a checkbox, and anything else falls back to a typed box
carrying whatever bounds the schema does state.

The screen is inert until the first preview returns, and says so. That first
render is the expensive one — the loop is sliced out of every stem and
time-stretched, minutes against milliseconds; `docs/architecture.md` carries
the measurements and what each of them includes — and it is also what
`preview.master_gain` calibrates from, so until it has happened there is no
level to play anything at. `Preview.isPlayable` is the single guard; nothing
here decides for itself whether it is usable.

-}

import Api
import Config
import Dict exposing (Dict)
import Html exposing (Attribute, Html, button, details, div, h2, h3, input, label, option, p, span, summary, text)
import Html.Attributes as Attr exposing (class, disabled, type_)
import Html.Events exposing (onCheck, onClick, onInput)
import Json.Decode as Decode
import Preview
import Schema
import Waveform


{-| What the mixer knows that nothing else does.

The song, its peaks and its loop region live in `Main` — they belong to the
song, not to this screen, and survive leaving it. Progress, solo and the config
being shaped do not: closing the mixer stops the audio and forgets them, which
is why they sit here and are thrown away wholesale.
-}
type alias State =
    { songId : String
    , progress : Float
    , solo : Maybe String
    , config : Config.Config
    }


init : String -> Schema.Schema -> List String -> State
init songId schema stemNames =
    { songId = songId
    , progress = 0
    , solo = Nothing
    , config = Config.fromSchema schema stemNames
    }


{-| What a preview of this state would be.

Total, so that `Main` never has to decide whether there is enough here to ask
for one — the only decision about sending lives in `Preview.request`.
-}
params : State -> Preview.Params
params state =
    { songId = state.songId
    , progress = state.progress
    , stems = soloedStems state
    , config = Config.encode state.config
    }


{-| The stems a preview should carry: one when something is soloed, and none at
all otherwise.

None is not silence. `Preview.encode` omits an empty list, and the server reads
a missing `stems` as "every stem the render would process" — so unsoloing
restores the whole mix by saying nothing, rather than by naming every stem and
risking a list that disagrees with what separation actually produced.

One soloed stem at a time. A set would allow every subset, including the empty
one, which encodes as "all" and would play the opposite of what the buttons
say.
-}
soloedStems : State -> List String
soloedStems state =
    case state.solo of
        Just name ->
            [ name ]

        Nothing ->
            []


toggleSolo : String -> State -> State
toggleSolo name state =
    { state
        | solo =
            if state.solo == Just name then
                Nothing

            else
                Just name
    }


{-| The scrubber's position, from the string an `<input type="range">` gives.

Clamped rather than trusted: `POST /api/preview` bounds `progress` to 0..1 and
422s outside it, and a value that cannot be parsed leaves the position where it
was rather than snapping to zero.
-}
setProgress : String -> State -> State
setProgress raw state =
    case String.toFloat raw of
        Just position ->
            { state | progress = clamp 0 1 position }

        Nothing ->
            state


setField : Schema.Schema -> Config.Target -> String -> State -> State
setField schema target raw state =
    { state | config = Config.set schema target raw state.config }


{-| Apply a checkbox, and drop a solo the checkbox has just invalidated.

Switching off the stem that is currently soloed asks the server for a mix of
exactly nothing. The Solo button is disabled on a switched-off stem, which
closes the solo-second order and nothing else: solo first, then uncheck
Enabled, and the button you are no longer looking at stays lit. That order used
to reach `POST /api/preview` and come back 200 with a one-frame WAV — silence
the browser plays without a word about why.

Clearing it here rather than filtering in `soloedStems` is the difference
between the state being unrepresentable and it merely being reported: nothing
downstream has to remember the combination exists.

-}
toggleField : Config.Target -> Bool -> State -> State
toggleField target on state =
    let
        updated =
            { state | config = Config.toggle target on state.config }
    in
    { updated | solo = soloAfter target on updated }


soloAfter : Config.Target -> Bool -> State -> Maybe String
soloAfter target on state =
    case ( target, on ) of
        ( Config.InStem index "enabled", False ) ->
            if state.solo == stemNameAt index state then
                Nothing

            else
                state.solo

        _ ->
            state.solo


stemNameAt : Int -> State -> Maybe String
stemNameAt index state =
    List.head (List.drop index state.config.stems) |> Maybe.map .name


{-| Is this stem's Enabled box ticked? Absent means yes — the schema's own
default, and the only reading that keeps a config which never mentions
`enabled` meaning "play it".
-}
stemEnabled : Config.Stem -> Bool
stemEnabled stem =
    Dict.get "enabled" stem.fields
        |> Maybe.andThen Config.asBool
        |> Maybe.withDefault True


{-| Nothing left to render: every stem the mixer is showing is switched off.

The server refuses this (400, `preview.render_window`) rather than playing the
default mix, which is what it used to do — but a refusal that arrives after the
request is a preview that stopped working for a reason the screen never states.
So `Main` does not send it, and the mixer says so instead. Empty is not this
case: a mixer with no stems at all cannot be opened.

-}
everyStemDisabled : State -> Bool
everyStemDisabled state =
    not (List.isEmpty state.config.stems)
        && List.all (stemEnabled >> not) state.config.stems


{-| The loop region the config is currently asking for, if it is asking for one.

Both absent is the ordinary case and means "detect it" — which is exactly what
`GET /api/songs/{id}/loop` does with no parameters, so the same call serves
both.
-}
loopOverride : State -> { startS : Maybe Float, endS : Maybe Float }
loopOverride state =
    let
        secondsAt key =
            Config.valueAt (Config.InSection "loop" key) state.config
                |> Maybe.andThen Config.asFloat
    in
    { startS = secondsAt "start_s", endS = secondsAt "end_s" }



-- VIEW


type alias Wiring msg =
    { onField : Config.Target -> String -> msg
    , onToggle : Config.Target -> Bool -> msg
    , enabled : Bool
    }


view :
    { state : State
    , song : Api.Song
    , schema : Schema.Schema
    , peaks : List ( Float, Float )
    , loop : Maybe Api.LoopRegion
    , preview : Preview.State
    , previewError : Maybe String
    , loopSeconds : Maybe Float
    , onBack : msg
    , onProgress : String -> msg
    , onSolo : String -> msg
    , onField : Config.Target -> String -> msg
    , onToggle : Config.Target -> Bool -> msg
    , onRetry : msg
    }
    -> Html msg
view config =
    let
        wiring =
            { onField = config.onField
            , onToggle = config.onToggle
            , enabled = Preview.isPlayable config.preview
            }
    in
    div [ class "mixer" ]
        [ button [ class "back", onClick config.onBack ] [ text "← Song" ]
        , h2 [] [ text config.song.title ]
        , Waveform.view
            { peaks = config.peaks
            , width = 960
            , height = 100
            , durationS = config.song.durationS
            , loop = Maybe.map (\r -> { startS = r.startS, endS = r.endS }) config.loop
            }
        , Waveform.caption config.loop
        , arcPanel config
        , stemsPanel wiring config.state config.schema config.onSolo
        , settingsPanel wiring config.state config.schema
        ]



-- THE ARC


arcPanel :
    { a
        | state : State
        , preview : Preview.State
        , previewError : Maybe String
        , loopSeconds : Maybe Float
        , onProgress : String -> msg
        , onRetry : msg
    }
    -> Html msg
arcPanel config =
    div [ class "arc" ]
        (if Preview.isPlayable config.preview then
            [ scrubber config
            , playingLine config
            , nothingToPlay config.state
            , previewProblem config
            ]

         else
            case config.previewError of
                -- Not playable *and* something went wrong: the opening preview
                -- failed, so nothing is being prepared and an animated bar
                -- would be claiming otherwise.
                Just _ ->
                    [ stalled, previewProblem config ]

                Nothing ->
                    [ preparing, previewProblem config ]
        )


stalled : Html msg
stalled =
    p [ class "dim" ]
        [ text
            ("There is nothing to play yet — the first preview did not come back, "
                ++ "so the controls stay inert until one does."
            )
        ]


scrubber :
    { a | state : State, onProgress : String -> msg }
    -> Html msg
scrubber config =
    div [ class "arc-row" ]
        [ span [ class "arc-label" ] [ text "Decay arc" ]
        , input
            [ type_ "range"
            , class "arc-scrub"
            , Attr.min "0"
            , Attr.max "1"
            , Attr.step "0.005"
            , Attr.value (String.fromFloat config.state.progress)
            , onInput config.onProgress
            ]
            []
        , span [ class "arc-value" ] [ text (arcPosition config.state) ]
        ]


{-| Where the scrubber is, said twice: as a fraction of the arc and as a point
in the finished mix, which is the thing anyone is actually asking about.

The minutes come from the config's own `output.duration_min`, so moving that
slider moves this readout too. If it is missing — the only way being a server
that stopped describing it — the percentage stands on its own.
-}
arcPosition : State -> String
arcPosition state =
    let
        percent =
            String.fromInt (round (state.progress * 100)) ++ "%"
    in
    case Config.valueAt (Config.InSection "output" "duration_min") state.config of
        Just (Config.FloatValue minutes) ->
            percent
                ++ " · "
                ++ String.fromInt (round (state.progress * minutes))
                ++ " min into a "
                ++ String.fromInt (round minutes)
                ++ " min mix"

        _ ->
            percent


playingLine : { a | loopSeconds : Maybe Float } -> Html msg
playingLine config =
    case config.loopSeconds of
        Just seconds ->
            p [ class "dim" ]
                [ text
                    ("Looping "
                        ++ String.fromInt (round seconds)
                        ++ " s of audio. Changes land at the next loop boundary, not "
                        ++ "under your finger — this auditions points in the arc, it is not a DAW."
                    )
                ]

        Nothing ->
            text ""


{-| The honest version of a spinner.

The wait behind this is real and long: slicing the loop out of every stem and
time-stretching each one — minutes on a full-length track, and more than that
when separation has to happen too; `docs/architecture.md` reconciles the
measurements — all of it inside a per-song lock with nothing reporting
progress. There is no
fraction to draw, so the bar does not pretend to be one — it moves because the
page is alive, and the words say what is happening and roughly what it costs.
A static "Preparing…" for two minutes reads as a hung application, and a
progress bar with no progress behind it would be a lie told in the one place
this project cares most about telling the truth.
-}
preparing : Html msg
preparing =
    div [ class "preparing" ]
        [ div [ class "preparing-track" ] [ div [ class "preparing-fill" ] [] ]
        , p []
            [ text
                ("Preparing the mixer — slicing the loop out of each stem and "
                    ++ "stretching it to the tempo you will hear."
                )
            ]
        , p [ class "dim" ]
            [ text
                ("On a full-length track this takes a minute or two. Everything after "
                    ++ "it is close to instant, because the stretched loops stay in memory "
                    ++ "for as long as this song is open. Nothing in that work reports "
                    ++ "progress, so the bar above only tells you the page is alive."
                )
            ]
        ]


{-| Said before the request goes out, not after it comes back 400.

The audio does not stop when the last stem is unticked — `Main` sends nothing,
so the previous preview keeps looping. Saying that outright is the point: a
mixer that goes on playing something while every control claims otherwise is
the same lie as one that plays a mix nobody asked for.
-}
nothingToPlay : State -> Html msg
nothingToPlay state =
    if everyStemDisabled state then
        p [ class "error" ]
            [ text
                ("Every stem is switched off, so there is nothing to render — "
                    ++ "what you can still hear is the last preview, looping. "
                    ++ "Switch a stem back on to hear the change."
                )
            ]

    else
        text ""


previewProblem : { a | previewError : Maybe String, onRetry : msg } -> Html msg
previewProblem config =
    case config.previewError of
        Nothing ->
            text ""

        Just reason ->
            div [ class "preview-error" ]
                [ p [ class "error" ] [ text ("The preview did not play — " ++ reason) ]
                , button [ onClick config.onRetry ] [ text "Try again" ]
                ]



-- STEMS


stemsPanel : Wiring msg -> State -> Schema.Schema -> (String -> msg) -> Html msg
stemsPanel wiring state schema onSolo =
    div [ class "stems" ]
        (h3 [] [ text "Stems" ]
            :: List.indexedMap (stemRow wiring state schema onSolo) state.config.stems
        )


stemRow : Wiring msg -> State -> Schema.Schema -> (String -> msg) -> Int -> Config.Stem -> Html msg
stemRow wiring state schema onSolo index stem =
    let
        enabled =
            stemEnabled stem

        soloed =
            state.solo == Just stem.name
    in
    div [ class "stem-row" ]
        [ div [ class "stem-head" ]
            [ span [ class "stem-name" ] [ text stem.name ]
            , button
                [ soloClass soloed
                , onClick (onSolo stem.name)

                -- Soloing a stem the config has switched off asks the server
                -- for a mix of nothing, which it refuses with a 400. This
                -- closes the solo-second order; `toggleField` closes the other
                -- one by clearing a solo the checkbox has invalidated.
                , disabled (not wiring.enabled || not enabled)
                ]
                [ text "Solo" ]
            ]
        , div [ class "fields" ]
            (controlsFor wiring state (Config.InStem index) (stemFields schema))
        , details [ class "decay" ]
            [ summary [] [ text "Decay" ]
            , p [ class "dim" ]
                [ text
                    ("Each of these is interpolated from its start to its end across "
                        ++ "the whole mix, so the loop erodes a little more every time round."
                    )
                ]
            , div [ class "fields" ]
                (controlsFor wiring state (Config.InStemDecay index) (sectionFields "stem_decay" schema))
            ]
        ]


{-| Two whole class strings rather than one built out of pieces.

`class (base ++ modifier)` reads better and hides the name: nothing can then
check that `solo-on` has a rule, and a class with no rule is an element with no
appearance. `tests/test_static_bundle.py` scans for string literals and rejects
the other spelling outright.
-}
soloClass : Bool -> Attribute msg
soloClass soloed =
    if soloed then
        class "solo solo-on"

    else
        class "solo"


{-| A stem's own controls: everything the `stem` section describes except its
name, which is the row you are looking at rather than something to choose. A
select there would offer to rename `drums` to `vocals` and change nothing about
what plays.
-}
stemFields : Schema.Schema -> Dict String Schema.Field
stemFields schema =
    Dict.remove "name" (sectionFields "stem" schema)


sectionFields : String -> Schema.Schema -> Dict String Schema.Field
sectionFields name schema =
    Dict.get name schema.sections
        |> Maybe.map .fields
        |> Maybe.withDefault Dict.empty



-- SETTINGS


settingsPanel : Wiring msg -> State -> Schema.Schema -> Html msg
settingsPanel wiring state schema =
    div [ class "settings" ]
        (section wiring state Config.Top "mix" (mixFields schema)
            :: List.map
                (\( name, aSection ) ->
                    section wiring state (Config.InSection name) name aSection.fields
                )
                (List.filter (\( name, _ ) -> not (List.member name [ "stem", "stem_decay" ]))
                    (Dict.toList schema.sections)
                )
        )


{-| The top-level config fields, minus `separation_model`.

Named explicitly rather than filtered by some rule, because there is exactly
one of these and a general mechanism for hiding config fields is the thing this
module exists not to have. It is excluded because it is not a mix-time setting
at all: `RenderSession.update_config` nulls `_stems` when it changes, and the
registry is built with the real `separate` function, so the next preview runs
Demucs — minutes, inside the per-song preview lock, with nothing reporting
progress, and the screen already playable so not even the preparing panel
shows. A typo committed on blur would fail somewhere deep in Demucs several
minutes later.

Every other control on this screen is a cheap re-render, which is the mixer's
whole contract; this one is not, and prose warning beside it is not a guard.
Giving it `choices` in `config.py` would make it a select instead of a text
box, which stops the typo and none of the rest. It belongs beside the Separate
button, where separation already has a progress bar and a job to watch.

The *value* still goes with every preview — `Config` carries the schema's
default and the server needs it to know which cached stems to use. Only the
control is gone.
-}
mixFields : Schema.Schema -> Dict String Schema.Field
mixFields schema =
    Dict.remove "separation_model" schema.fields


section : Wiring msg -> State -> (String -> Config.Target) -> String -> Dict String Schema.Field -> Html msg
section wiring state toTarget name fields =
    details [ class "section" ]
        [ summary [] [ text (titleOf name) ]
        , sectionNote name
        , div [ class "fields" ] (controlsFor wiring state toTarget fields)
        ]


titleOf : String -> String
titleOf name =
    case String.uncons (String.replace "_" " " name) of
        Just ( first, rest ) ->
            String.toUpper (String.fromChar first) ++ rest

        Nothing ->
            name


{-| What the server does with a section that the schema has no way to say.

Three of these are about cost — a loop or tempo change throws away every
stretched loop, and a different separation model throws away the stems as
well — and one is about a section the preview does not render at all. Both
kinds are the sort of thing you otherwise learn by changing a slider, hearing
nothing, and concluding the mixer is broken. Sections not named here get no
note, which is what makes this safe to leave alone as the config grows.
-}
sectionNote : String -> Html msg
sectionNote name =
    let
        note =
            case name of
                "loop" ->
                    Just
                        ("Changing where the loop is means finding and stretching it "
                            ++ "again, so the next preview takes as long as the first did. "
                            ++ "The region drawn above follows an explicit start and end; "
                            ++ "the rest of these apply when the loop is detected for you."
                        )

                "tempo" ->
                    Just
                        ("Every stem is stretched again after a change here, so the next "
                            ++ "preview takes as long as the first did."
                        )

                "soundbed" ->
                    Just "The sound bed is mixed in when you render. Previews never include it."

                "output" ->
                    Just
                        ("Duration decides how many repetitions the arc is spread over, so "
                            ++ "it changes what any point in it sounds like. The fades apply "
                            ++ "to the finished mix only, and so does the sample rate — a "
                            ++ "preview always plays at the rate the stems were separated at."
                        )

                "mix" ->
                    Just
                        ("The separation model is not here on purpose: changing it "
                            ++ "separates the song again from scratch, which is minutes "
                            ++ "of silence rather than a re-render. It belongs beside "
                            ++ "the Separate button, which has a progress bar."
                        )

                _ ->
                    Nothing
    in
    case note of
        Just words ->
            p [ class "section-note" ] [ text words ]

        Nothing ->
            text ""



-- CONTROLS


controlsFor : Wiring msg -> State -> (String -> Config.Target) -> Dict String Schema.Field -> List (Html msg)
controlsFor wiring state toTarget fields =
    List.map
        (\( key, spec ) -> control wiring state (toTarget key) spec)
        (Dict.toList fields)


control : Wiring msg -> State -> Config.Target -> Schema.Field -> Html msg
control wiring state target spec =
    case spec of
        Schema.BoolField s ->
            checkbox wiring state target s

        Schema.FloatField s ->
            number wiring state target s

        Schema.IntField s ->
            number wiring state target s

        Schema.TextField s ->
            typedBox wiring state target { label = s.label, help = s.help, unit = Nothing } "text" []

        Schema.StringChoiceField s ->
            chooser wiring state target { label = s.label, help = s.help } s.choices

        Schema.IntChoiceField s ->
            chooser wiring state target { label = s.label, help = s.help } (List.map String.fromInt s.choices)


checkbox : Wiring msg -> State -> Config.Target -> { a | label : String, help : Maybe String, default : Bool } -> Html msg
checkbox wiring state target spec =
    let
        on =
            Config.valueAt target state.config
                |> Maybe.andThen Config.asBool
                |> Maybe.withDefault spec.default
    in
    label [ class "field field-check", help spec.help ]
        [ input
            [ type_ "checkbox"
            , Attr.checked on
            , onCheck (wiring.onToggle target)
            , disabled (not wiring.enabled)
            ]
            []
        , span [ class "field-label" ] [ text spec.label ]
        ]


{-| A slider where the schema gives a range to slide along, a typed box
otherwise.

All three of `min`, `max` and `step` or none of it: a range input with no step
snaps to integers, which turns a 0..1 reverb send into an on/off switch, and one
with no maximum has nowhere to put the thumb. `loop.start_s` is the field this
matters for — it carries a minimum and nothing else, because the maximum is the
length of whichever song you happen to have open.
-}
number :
    Wiring msg
    -> State
    -> Config.Target
    ->
        { a
            | label : String
            , help : Maybe String
            , min : Maybe Float
            , max : Maybe Float
            , step : Maybe Float
            , unit : Maybe String
        }
    -> Html msg
number wiring state target spec =
    let
        bounds =
            List.filterMap identity
                [ Maybe.map (Attr.min << String.fromFloat) spec.min
                , Maybe.map (Attr.max << String.fromFloat) spec.max
                , Maybe.map (Attr.step << String.fromFloat) spec.step
                ]
    in
    case ( spec.min, spec.max, spec.step ) of
        ( Just _, Just _, Just _ ) ->
            div [ class "field", help spec.help ]
                [ span [ class "field-label" ] [ text spec.label ]
                , input
                    (type_ "range"
                        :: class "field-range"
                        :: Attr.value (reading state target)
                        :: onInput (wiring.onField target)
                        :: disabled (not wiring.enabled)
                        :: bounds
                    )
                    []
                , span [ class "field-value" ]
                    [ text (reading state target ++ unitSuffix spec.unit) ]
                ]

        _ ->
            typedBox wiring state target { label = spec.label, help = spec.help, unit = spec.unit } "number" bounds


typedBox :
    Wiring msg
    -> State
    -> Config.Target
    -> { label : String, help : Maybe String, unit : Maybe String }
    -> String
    -> List (Attribute msg)
    -> Html msg
typedBox wiring state target spec kind bounds =
    div [ class "field", help spec.help ]
        [ span [ class "field-label" ] [ text (spec.label ++ unitSuffix spec.unit) ]
        , input
            (type_ kind
                :: class "field-box"
                :: Attr.value (reading state target)
                :: onCommit (wiring.onField target)
                :: disabled (not wiring.enabled)
                :: bounds
            )
            []
        ]


{-| A typed box reports when you leave it, not on every keystroke.

Not a preference — `onInput` makes these boxes unusable. Half-typed text is not
a number, `Config.set` drops the key for anything it cannot parse, and the
value attribute then re-renders as empty and takes the half-typed text with it:
you can enter `1`, and you cannot enter `1.5`, because `1.` never survives long
enough to become it.

It is also the right economics. `loop.start_s` and `loop.end_s` each re-fetch
the loop region, which decodes the whole file and runs beat tracking with no
cache — five keystrokes would be five of those, where this is one.

A range or a select has neither problem: every value they can produce is a
value, so those keep firing continuously, which is the drag the preview state
machine exists to coalesce.
-}
onCommit : (String -> msg) -> Attribute msg
onCommit toMsg =
    Html.Events.on "change" (Decode.map toMsg Html.Events.targetValue)


chooser :
    Wiring msg
    -> State
    -> Config.Target
    -> { label : String, help : Maybe String }
    -> List String
    -> Html msg
chooser wiring state target spec choices =
    let
        current =
            reading state target
    in
    div [ class "field", help spec.help ]
        [ span [ class "field-label" ] [ text spec.label ]
        , Html.select
            [ class "field-select"
            , onInput (wiring.onField target)
            , disabled (not wiring.enabled)
            ]
            (List.map
                (\choice ->
                    option [ Attr.value choice, Attr.selected (choice == current) ]
                        [ text choice ]
                )
                choices
            )
        ]


{-| The value a control should show. Empty when the config is not carrying the
key, which is a real state and means "whatever the server decides" — see
`Config`'s note on nullable defaults.
-}
reading : State -> Config.Target -> String
reading state target =
    Config.valueAt target state.config
        |> Maybe.map Config.valueString
        |> Maybe.withDefault ""


unitSuffix : Maybe String -> String
unitSuffix unit =
    case unit of
        Just u ->
            " " ++ u

        Nothing ->
            ""


{-| The schema's `help` as a tooltip. Empty rather than absent when there is
none: browsers show nothing for an empty `title`, and an attribute that is
sometimes there and sometimes not costs a conditional at every call site.
-}
help : Maybe String -> Attribute msg
help words =
    Attr.title (Maybe.withDefault "" words)
