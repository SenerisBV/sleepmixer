module Page.Mixer exposing
    ( Pending(..), State
    , everyStemDisabled, init, loopOverride, params, preflight, renderBlock
    , renderConfig, setField, setProgress, soloedStems, toggleField, toggleSolo
    , applyPreset, armConfirm, lastUsed, newPresetName, presetById, presetSaved
    , saveMessage, saveOverAvailable, selectPreset, selection, setPresetName
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
import Http
import Json.Decode as Decode
import Json.Encode as Encode
import Page.Renders as Renders
import Preview
import Schema
import Warn
import Waveform


{-| What the mixer knows that nothing else does.

The song, its peaks and its loop region live in `Main` — they belong to the
song, not to this screen, and survive leaving it. Progress, solo and the config
being shaped do not: closing the mixer stops the audio and forgets them, which
is why they sit here and are thrown away wholesale.

The preset bar's three fields are the same argument again. Which preset the
select is on, what is typed in the name box and which destructive button is
awaiting a confirm are all facts about this sitting at this screen — the
presets themselves live in `Main`, because they outlive it and are the same for
every song. `selectedPreset` is an id rather than a preset so that a list
re-fetched after a save or a delete is the only thing that decides whether it
still resolves; see `selection`.

`openedAtSchemaDefaults` is a fact about the config this screen *started* from
and is therefore recorded when it opens rather than read off the model later. A
mixer that opened before `GET /api/config/default` answered is at the schema's
defaults for the rest of its life, whatever the model holds by the time anyone
looks.
-}
type alias State =
    { songId : String
    , progress : Float
    , solo : Maybe String
    , config : Config.Config
    , selectedPreset : Maybe String
    , presetName : String
    , pending : Maybe Pending
    , openedAtSchemaDefaults : Bool
    }


{-| A destructive button that has been pressed once and is waiting to be meant.

Both of these are one click from Apply and neither is undoable — a preset saved
over does not keep what it held, and a deleted one is gone from a table nothing
else references. `window.confirm` is not reachable from Elm without a port, and
a port for a yes/no is a worse trade than a sentence and two buttons, which is
also the only version `elm-test` can press.
-}
type Pending
    = SaveOver
    | Delete


{-| The starting point for a config: the schema's defaults, laid over with the
server's published config when there is one.

`Config.fromSchema` alone is a *different starting point* from the one
`sleepmix render` uses, and the difference is on every stem: the schema
describes each field of one stem and has no way to describe a list, so it
gives every stem the same values, while `MixConfig` curates four — drums off,
bass decay off, vocals on an `exp` curve to 2200 Hz, other on `linear` to
2400 Hz. Laying `GET /api/config/default` over the schema's defaults is what
closes that, and it is laid over rather than used raw because the schema is
still the authority on which keys may exist and what bounds they are held to
(`Config.overlay`).

`Nothing` is the fallback, not the absence of a decision.

**`init` and `applyPreset` share this rather than each building their own base
from `Config.fromSchema`.** They used to agree only by coincidence — every
scalar leaf's schema default already equals the dataclass default, so the two
bases matched everywhere except the one place `MixConfig` curates a list the
schema cannot describe: the stems. A preset that does not name a stem, or a
song whose stem set does not match the one a preset was saved from, used to
fall all the way back to the schema's uniform values instead of the curated
ones — silently, because `defaultsNote` had no way to know a *different*
default had just been reintroduced. Sharing one function is what keeps that
from opening back up the next time either caller changes.
-}
baseConfig : Schema.Schema -> List String -> Maybe Decode.Value -> Config.Config
baseConfig schema stemNames defaults =
    let
        base =
            Config.fromSchema schema stemNames
    in
    case defaults of
        Just published ->
            Config.overlay schema published base

        Nothing ->
            base


{-| Open the mixer, over the server's own default config when there is one.

`Nothing` is the fallback, not the absence of a decision: the mixer opens
anyway, because a screen that will not open because one fetch failed is worse
than one that opens at a starting point it can name — and it names it, in
`defaultsNote`.
-}
init : String -> Schema.Schema -> List String -> Maybe Decode.Value -> State
init songId schema stemNames defaults =
    { songId = songId
    , progress = 0
    , solo = Nothing
    , config = baseConfig schema stemNames defaults
    , selectedPreset = Nothing
    , presetName = ""
    , pending = Nothing
    , openedAtSchemaDefaults =
        case defaults of
            Just _ ->
                False

            Nothing ->
                True
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


-- PRESETS


{-| The preset an id names, if the list still has one.

Every question the bar asks goes through this, because every one of them is
"does this id still resolve" — the select's own selection, the "last used here"
line, and whether Save over and Delete have anything to act on. A preset
deleted a moment ago is an id that resolves to nothing, and nothing is exactly
what each of those should then offer.
-}
presetById : List Api.Preset -> Maybe String -> Maybe Api.Preset
presetById presets wanted =
    case wanted of
        Nothing ->
            Nothing

        Just id ->
            List.head (List.filter (\preset -> preset.id == id) presets)


{-| Which preset the select is on.

Held as an id and resolved against the list every time rather than stored as a
preset, so a list re-fetched after a delete drops the selection by itself: there
is no way to be selecting a preset that is no longer there.
-}
selection : List Api.Preset -> State -> Maybe Api.Preset
selection presets state =
    presetById presets state.selectedPreset


{-| Is there a preset to save over, or delete?

The same question as `selection` and stated separately because it is what two
buttons are disabled by — a `Bool` at the call site rather than a `Maybe`
compared to `Nothing` in the markup.
-}
saveOverAvailable : List Api.Preset -> State -> Bool
saveOverAvailable presets state =
    case selection presets state of
        Just _ ->
            True

        Nothing ->
            False


{-| The preset this song last had applied, if it still exists.

`songs.last_preset_id` is deliberately not a foreign key, so deleting a preset
leaves the id dangling on every song that pointed at it. Resolving it here is
what turns that into nothing at all rather than into a line with an empty name
in it — and nothing at all is the right answer, because the recipe it named no
longer exists to apply.
-}
lastUsed : List Api.Preset -> Api.Song -> Maybe Api.Preset
lastUsed presets song =
    presetById presets song.lastPresetId


{-| The name to save under, or nothing to save under at all.

Trimmed, because `presets.name` is `NOT NULL UNIQUE` and a name that is
whitespace either side of a word is a second row that reads identically to the
first in the select.
-}
newPresetName : State -> Maybe String
newPresetName state =
    case String.trim state.presetName of
        "" ->
            Nothing

        trimmed ->
            Just trimmed


setPresetName : String -> State -> State
setPresetName raw state =
    { state | presetName = raw }


{-| Choose a preset in the select, or choose none — the placeholder option
carries an empty value, which is the only value the select can produce that is
not an id.

A confirm armed against the *previous* selection is dropped, because the
sentence beside it names a preset and the button under it would act on this
one. That is a two-click path to deleting something nobody meant to.
-}
selectPreset : String -> State -> State
selectPreset raw state =
    { state
        | selectedPreset =
            if String.isEmpty raw then
                Nothing

            else
                Just raw
        , pending = Nothing
    }


armConfirm : Maybe Pending -> State -> State
armConfirm pending state =
    { state | pending = pending }


{-| A preset that has just been created: it becomes the selection, and the name
box is empty again so the next Save as… is not pre-loaded with the last one.
-}
presetSaved : Api.Preset -> State -> State
presetSaved preset state =
    { state | selectedPreset = Just preset.id, presetName = "", pending = Nothing }


{-| Make the mixer look like this preset — and leave this song's loop region
where it is.

Built over `baseConfig` — the same base `init` opens on, not the config on
screen and not a bare `Config.fromSchema` — because apply means *make it look
like this* and not *merge this in*: a field the preset does not carry goes back
to its default rather than keeping a value from the recipe the operator
believes they have just replaced. And "its default" has to mean the same thing
here as it did when the mixer opened: a preset that is silent about a stem, or
a song whose stems do not match the ones the preset was saved from, must land
that stem on the server's curated default and not the schema's flatter one —
see `baseConfig`.

**The loop region is the exception, and it is carried explicitly because
nothing else would carry it.** `loop.start_s` and `loop.end_s` have a `null`
schema default, so `fromSchema` omits them entirely, and `Config.forPreset`
strips them from every preset that is saved — so a plain overlay silently
reverts a region the operator chose on *this song* back to auto-detection, with
no control on screen changing to say so. They are seconds into one particular
piece of audio; they belong to the song, and applying a recipe is not a
statement about them either way.

Carried in both directions: a preset written by an older build could carry
seconds measured on different audio, and a mixer that is auto-detecting its
loop must go on auto-detecting it rather than adopt them.
-}
applyPreset : Schema.Schema -> Maybe Decode.Value -> Api.Preset -> State -> State
applyPreset schema defaults preset state =
    let
        applied =
            baseConfig schema (List.map .name state.config.stems) defaults
                |> Config.overlay schema preset.config
    in
    { state
        | config = carryLoopRegion schema state.config applied
        , selectedPreset = Just preset.id
        , pending = Nothing
    }


{-| The two loop fields of `from`, written over whatever `into` has for them.

Through `Config.set`, which is the same door every typed control uses: a value
is rendered back to the string the box would have held and re-parsed under the
schema's own bounds, and an absent one is set to `""`, which is how `Config.set`
is told to remove a key. Absent means "detect the loop yourself", so removing
is as load-bearing as inserting.
-}
carryLoopRegion : Schema.Schema -> Config.Config -> Config.Config -> Config.Config
carryLoopRegion schema from into =
    List.foldl (carryLoopKey schema from) into [ "start_s", "end_s" ]


carryLoopKey : Schema.Schema -> Config.Config -> String -> Config.Config -> Config.Config
carryLoopKey schema from key into =
    let
        target =
            Config.InSection "loop" key
    in
    Config.set schema
        target
        (Config.valueAt target from
            |> Maybe.map Config.valueString
            |> Maybe.withDefault ""
        )
        into


{-| What to say when a save is refused.

Both statuses are reachable by ordinary use and neither may fail silently. The
409 is the one the operator causes: two setups saved under one name, where the
server refuses the second rather than replacing the first — Save over is the
button for that, and the sentence points at it. The 400 is the server's own
validation, which runs `MixConfig.from_dict` before storing anything.

**The server's own `detail` does not reach this side.** `Http.expectJson`
discards the body of a non-2xx response, so an `Http.BadStatus` carries a
number and nothing else — the `detail` argument here is
`Main.httpErrorToString`'s "the server answered 400", not the sentence the
route raised. So the 400 branch says where the reason is rather than pretending
to quote it. Carrying it would mean `expectStringResponse` in `Request.elm` and
a decode of the error body, which is a change to an interface this task
consumes rather than owns; what is not acceptable is a message that claims to
explain and does not.

Takes the generic wording rather than deriving it, exactly as
`Page.Renders.deleteMessage` does, so `Main.httpErrorToString` stays the one
place an `Http.Error` becomes English.
-}
saveMessage : Http.Error -> String -> String
saveMessage err detail =
    case err of
        Http.BadStatus 409 ->
            "There is already a preset with that name. Pick another, or select "
                ++ "that one and use Save over to replace what it holds."

        Http.BadStatus 400 ->
            "The server refused that config. It validates a preset before "
                ++ "storing it, so a recipe that could never render fails here "
                ++ "rather than at render time — but it says why in its own log "
                ++ "and not in an answer this screen can read."

        Http.BadStatus 404 ->
            "That preset is no longer there — it was deleted while this screen "
                ++ "was open."

        _ ->
            "Could not save that preset — " ++ detail



-- STARTING A RENDER


{-| The config a render should be made from.

`Config.encode` and nothing else — the same encoder every preview carries, so
the mix that comes out is the one you have been listening to. It is a function
here rather than `Config.encode state.config` written out in `Main` so that the
thing which must *not* travel with it has somewhere to be said: `params` also
carries a `stems` list holding the soloed stem, and a render must not honour
it. Solo is a way to hear one stem while you shape it, not a decision about
what goes into the mix — a render that obeyed it would produce half an hour of
drums from a screen whose every other control said otherwise.
-}
renderConfig : State -> Encode.Value
renderConfig state =
    Config.encode state.config


{-| Why the Render button cannot be pressed, if it cannot.

The sentence rather than a `Bool`, for the reason `Page.Song.mixerPanel` gives
one screen along: a control that is greyed out and says nothing about why is a
screen refusing to explain itself.

Two reasons, and deliberately not a third. It is **not** gated on the preview
being playable, although every other control here is. A render is server-side
work that has nothing to do with whether this browser could decode a preview
WAV, so gating on that would turn a playback failure into "you cannot produce a
mix at all" — which is the exact thing this button exists to stop being true.
What you get in that case is the config as it stands, which the pre-flight line
above states in full.
-}
renderBlock : Bool -> State -> Maybe String
renderBlock starting state =
    if starting then
        Just
            ("Starting it — this moves to the renders screen as soon as the "
                ++ "server has taken it."
            )

    else if everyStemDisabled state then
        Just
            ("Every stem is switched off, so there is nothing to render — the "
                ++ "server refuses a mix of nothing, and it would be right to."
            )

    else
        Nothing


{-| What pressing Render is about to do, said before it does it.

Two facts, and which two is the point. The mix length, because it is the number
that decides how much work this is and it is one the operator has just been
moving — the scrubber's own readout quotes the same `output.duration_min`.
And whether the stems are already separated, because that is the difference
between a render that starts on the render and one that runs Demucs first:
minutes before anything else happens, and by far the largest term in how long
this takes.

**And no estimate of that time**, though the ordering above is no longer a
guess. One render has been measured end to end: a 246.6 s source at the default
20-minute output, stems already cached, finished in 13.6 s wall-clock and 11.0 s
on a second run — roughly 13:1 against the cold preview figure measured at 180.55 s. So
a render from warm stems really is the cheap half and separation really is the
expensive one, which is what the second phrase on this line is for.

What has *not* been measured is everything an estimate would need: a cold
cache, a source that is not four minutes, a machine that is not this one. Two
warm runs of one track is a measurement, not a model, and a number stated here
would be read as the model. The "Preparing…" panel a few lines up is
deliberately indeterminate for the same reason, and a bar that lies about time
left is the one lie this interface is built not to tell. If a ratio is ever
measured widely enough to be stable, an estimate can become something this line
claims; until then it does not.
-}
preflight : Bool -> State -> String
preflight stemsSeparated state =
    lengthPhrase state ++ " " ++ stemsPhrase stemsSeparated


{-| `Renders.minutesLabel` rather than a rounding written here, so the length
this screen promises and the length the renders screen reports are said by one
function. It also handles the case a bare `round` gets wrong: the 0.05-minute
configs this project's own tests render would otherwise read "0 min".

Absent is a real state and gets its own sentence rather than a zero.
`Config.set` removes a key it cannot parse, and absent means "whatever the
server decides" throughout this module — so claiming a length here would be
claiming one nobody has stated.
-}
lengthPhrase : State -> String
lengthPhrase state =
    case Maybe.andThen Config.asFloat (Config.valueAt (Config.InSection "output" "duration_min") state.config) of
        Just minutes ->
            "About to render a " ++ Renders.minutesLabel minutes ++ " mix."

        Nothing ->
            "About to render a mix of whatever length the server defaults to — "
                ++ "this config is not carrying one."


{-| Asked rather than assumed, though the answer is always yes today:
`Page.Song.mixerPanel` refuses to open this screen on a song with no stems, so
a mixer without them is unreachable. The gate is one screen away and could move;
a sentence that asserts the stems are cached without looking would be a claim
this module never checked, and it would be wrong silently — the render would
simply take an extra Demucs run that nothing had mentioned.
-}
stemsPhrase : Bool -> String
stemsPhrase stemsSeparated =
    if stemsSeparated then
        "The stems are already separated, so the worker starts on the render itself."

    else
        "The stems are not separated yet, so that runs first — minutes of it, "
            ++ "before the render begins."


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
    , startingRender : Bool
    , renderError : Maybe String
    , presets : List Api.Preset
    , presetProblem : Maybe String
    , onBack : msg
    , onProgress : String -> msg
    , onSolo : String -> msg
    , onField : Config.Target -> String -> msg
    , onToggle : Config.Target -> Bool -> msg
    , onRetry : msg
    , onRender : msg
    , onPresetSelected : String -> msg
    , onPresetApplied : String -> msg
    , onPresetName : String -> msg
    , onPresetSaveAs : msg
    , onPresetPending : Maybe Pending -> msg
    , onPresetSaveOver : msg
    , onPresetDelete : msg
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

        -- Above the arc, because a preset is the recipe every control below it
        -- is a detail of: you pick one, then you shape it. It is also the one
        -- row on this screen that changes every other control at once, which
        -- is a thing to see before you start moving them.
        , presetBar config
        , arcPanel config

        -- Directly under the arc rather than at the foot of the screen. A
        -- render is the arc committed to a file: it quotes the same
        -- `output.duration_min` the scrubber's readout just quoted, and
        -- putting it here means the one control that produces a mix is not
        -- below four stem panels and every generated settings section. Nobody
        -- writing this can open a browser to check what is above the fold, so
        -- it goes where it is certainly visible.
        , renderPanel config
        , stemsPanel wiring config.state config.schema config.onSolo
        , settingsPanel wiring config.state config.schema
        ]



-- THE PRESET BAR


{-| Saved recipes: apply one, save this one, or throw one away.

A row rather than a screen. Presets are applied *here*, against the controls
they move and while a preview is playing, so a screen of their own would be a
second place to navigate to for what is one row — and you would be looking at
the preset list rather than at the mixer it changes.

Every decision on it is a pure function above, so `elm-test` reaches all of
them: which preset is selected, whether there is one to save over, whether the
"last used here" line resolves, and what a refused save says. What is left here
is markup and wiring.
-}
presetBar :
    { a
        | state : State
        , song : Api.Song
        , presets : List Api.Preset
        , presetProblem : Maybe String
        , preview : Preview.State
        , onPresetSelected : String -> msg
        , onPresetApplied : String -> msg
        , onPresetName : String -> msg
        , onPresetSaveAs : msg
        , onPresetPending : Maybe Pending -> msg
        , onPresetSaveOver : msg
        , onPresetDelete : msg
    }
    -> Html msg
presetBar config =
    let
        chosen =
            selection config.presets config.state

        blocked =
            applyBlock config.preview chosen
    in
    div [ class "presets" ]
        [ div [ class "preset-row" ]
            [ span [ class "preset-label" ] [ text "Preset" ]
            , presetSelect config chosen
            , button
                [ class "preset-apply"
                , onClick (config.onPresetApplied (Maybe.withDefault "" (Maybe.map .id chosen)))
                , disabled (blocked /= Nothing)
                ]
                [ text "Apply" ]
            , button
                [ class "preset-save-over"
                , onClick (config.onPresetPending (Just SaveOver))
                , disabled (not (saveOverAvailable config.presets config.state))
                ]
                [ text "Save over…" ]
            , button
                [ class "preset-delete"
                , onClick (config.onPresetPending (Just Delete))
                , disabled (not (saveOverAvailable config.presets config.state))
                ]
                [ text "Delete…" ]
            ]
        , case blocked of
            Just words ->
                p [ class "dim" ] [ text words ]

            Nothing ->
                text ""
        , div [ class "preset-row" ]
            [ span [ class "preset-label" ] [ text "New preset" ]
            , input
                [ type_ "text"
                , class "preset-name"
                , Attr.value config.state.presetName
                , Attr.placeholder "Name this setup"
                , onInput config.onPresetName
                ]
                []
            , button
                [ class "preset-save"
                , onClick config.onPresetSaveAs

                -- A `POST` with an empty name is a 422 from the server and a
                -- row with no name in the select if it ever got past one.
                , disabled (newPresetName config.state == Nothing)
                ]
                [ text "Save as…" ]
            ]
        , confirmLine config chosen
        , lastUsedLine config
        , case config.presetProblem of
            Just words ->
                p [ class "error" ] [ text words ]

            Nothing ->
                text ""
        , defaultsNote config.state
        ]


{-| The saved presets, in the order `GET /api/presets` answered — by name,
which is the only order a list of recipes has.

The first option is a placeholder carrying an empty value, and it is what makes
"nothing selected" a state the browser and the model agree on. Without it the
select would show the first preset while the model held no selection, and
Delete would be one click from removing a preset nobody chose.
-}
presetSelect :
    { a | presets : List Api.Preset, onPresetSelected : String -> msg }
    -> Maybe Api.Preset
    -> Html msg
presetSelect config chosen =
    let
        chosenId =
            Maybe.withDefault "" (Maybe.map .id chosen)
    in
    Html.select
        [ class "preset-select", onInput config.onPresetSelected ]
        (option [ Attr.value "", Attr.selected (chosenId == "") ] [ text "— no preset —" ]
            :: List.map
                (\preset ->
                    option
                        [ Attr.value preset.id, Attr.selected (preset.id == chosenId) ]
                        [ text preset.name ]
                )
                config.presets
        )


{-| Why Apply cannot be pressed, if it cannot — the sentence rather than a
`Bool`, for the reason `renderBlock` gives about the Render button.

Readiness is asked *first*, and that ordering is the fix to a screen that
refused to explain itself: with the selection asked first, a mixer still
preparing with nothing chosen said only "choose a preset", and the "Last used
here" line's Apply — which needs no selection at all — sat greyed out with
nothing on screen accounting for it. Both buttons are inert for the same
reason at that moment, so the same sentence has to be the one showing.

Why they are inert is worth the sentence. Applying while the opening preview is
still in flight would move every control on the screen and change nothing about
what you are about to hear: `Preview.request` refuses while `Warming`, and the
preview already in flight is of the config from before the apply. The mixer
would then be showing one recipe and playing another, which is the single thing
this screen must never do.
-}
applyBlock : Preview.State -> Maybe Api.Preset -> Maybe String
applyBlock preview chosen =
    if not (Preview.isPlayable preview) then
        Just
            ("The mixer is still preparing, so nothing can be applied yet — "
                ++ "doing it now would move every control without changing what "
                ++ "you hear. Both Apply buttons become live as soon as the first "
                ++ "preview plays."
            )

    else
        case chosen of
            Nothing ->
                Just
                    ("Choose a preset to apply. Applying replaces every setting below, "
                        ++ "including the ones the preset does not mention — it is "
                        ++ "\"make it look like this\", not \"merge this in\"."
                    )

            Just _ ->
                Nothing


{-| A destructive button, pressed once, asking to be meant.

Both of these are irreversible and both sit one button away from Apply, which
is pressed constantly. The sentence names the preset, so a confirm cannot be
answered about a different one than it was armed for — and `selectPreset`
disarms it when the selection moves, so it cannot go stale either.
-}
confirmLine :
    { a
        | state : State
        , onPresetPending : Maybe Pending -> msg
        , onPresetSaveOver : msg
        , onPresetDelete : msg
    }
    -> Maybe Api.Preset
    -> Html msg
confirmLine config chosen =
    case ( config.state.pending, chosen ) of
        ( Just SaveOver, Just preset ) ->
            confirmRow config
                ("Replace “"
                    ++ preset.name
                    ++ "” with what is on screen? What it holds now is not kept anywhere."
                )
                "Save over it"
                config.onPresetSaveOver

        ( Just Delete, Just preset ) ->
            confirmRow config
                ("Delete “"
                    ++ preset.name
                    ++ "”? Any song that remembers it will simply stop showing it."
                )
                "Delete it"
                config.onPresetDelete

        _ ->
            text ""


confirmRow :
    { a | onPresetPending : Maybe Pending -> msg }
    -> String
    -> String
    -> msg
    -> Html msg
confirmRow config question wording onConfirm =
    p [ class "preset-confirm" ]
        [ span [ class "preset-question" ] [ text question ]
        , button [ class "preset-go", onClick onConfirm ] [ text wording ]
        , button [ class "preset-keep", onClick (config.onPresetPending Nothing) ]
            [ text "Keep it" ]
        ]


{-| What was last applied to *this song*, when it still exists.

A shortcut for the opt-in and not a weakening of it: nothing is applied
automatically, because a preset that re-applied itself would mean editing one
silently changes songs tuned weeks ago. So this is a name and a button, and the
button is the same one the bar's own Apply presses.

Absent entirely when the id does not resolve — see `lastUsed`.
-}
lastUsedLine :
    { a
        | song : Api.Song
        , presets : List Api.Preset
        , preview : Preview.State
        , onPresetApplied : String -> msg
    }
    -> Html msg
lastUsedLine config =
    case lastUsed config.presets config.song of
        Nothing ->
            text ""

        Just preset ->
            p [ class "preset-last" ]
                [ span [ class "dim" ] [ text "Last used here: " ]
                , span [ class "preset-last-name" ] [ text preset.name ]
                , button
                    [ class "preset-last-apply"
                    , onClick (config.onPresetApplied preset.id)
                    , disabled (not (Preview.isPlayable config.preview))
                    ]
                    [ text "Apply" ]
                ]


{-| Said when this mixer opened without the server's own defaults.

Falling back to the schema's defaults is the right call — a mixer that will not
open because one fetch failed is worse than one that opens somewhere it can
name — but doing it silently would re-open the gap the default-config route was
added to close, and the gap is audible: every stem erodes identically, where a
render at defaults does not.
-}
defaultsNote : State -> Html msg
defaultsNote state =
    if state.openedAtSchemaDefaults then
        p [ class "mixer-defaults" ]
            [ text
                ("This mixer opened at the schema's own defaults: the server's "
                    ++ "default config had not arrived. Every stem therefore starts "
                    ++ "identical, where a render at defaults starts with drums off, "
                    ++ "bass decay off, and the vocal and other stems eroding on "
                    ++ "curves of their own. Leave the mixer and open it again to "
                    ++ "start from the server's."
                )
            ]

    else
        text ""



-- THE RENDER BUTTON


{-| The way out of auditioning and into a file.

Every decision on it is in a pure function above — what the line says, and
whether the button can be pressed — so `elm-test` can reach both. What is left
here is markup.
-}
renderPanel :
    { a
        | state : State
        , song : Api.Song
        , startingRender : Bool
        , renderError : Maybe String
        , onRender : msg
    }
    -> Html msg
renderPanel config =
    let
        blocked =
            renderBlock config.startingRender config.state
    in
    div [ class "render-start" ]
        [ p [] [ text (preflight (not (List.isEmpty config.song.stems)) config.state) ]
        , longSourceWarning config.song.durationS
        , button
            [ class "render-go"
            , onClick config.onRender
            , disabled (blocked /= Nothing)
            ]
            [ text "Render this mix" ]
        , case blocked of
            Just words ->
                p [ class "dim" ] [ text words ]

            Nothing ->
                text ""
        , case config.renderError of
            Just reason ->
                p [ class "error" ] [ text ("Could not start that render — " ++ reason) ]

            Nothing ->
                text ""
        ]


{-| The long-source warning, taken from `Warn` rather than written here.

The song screen shows the same sentence beside its Separate button, and the two
must not drift into stating different rules about the same single worker — that
is the whole reason `Warn` is a module. Only the markup is local, and `.warn`
is the class on both sides so they read alike as well.
-}
longSourceWarning : Float -> Html msg
longSourceWarning durationS =
    case Warn.forSource durationS of
        Warn.Long words ->
            p [ class "warn" ] [ text words ]

        Warn.NoWarning ->
            text ""



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
