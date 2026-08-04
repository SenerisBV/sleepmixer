module Page.Song exposing (buttonLabel, needsForce, view)

{-| One song: what it is, what it looks like, and whether it has been split.

The separation reason is shown rather than swallowed. It exists precisely so
that someone who asked for four stems and got one is told why, instead of
being left to wonder whether the tool is broken.
-}

import Api
import Html exposing (Html, button, div, h2, p, span, text)
import Html.Attributes exposing (class, disabled)
import Html.Events exposing (onClick)
import Waveform


view :
    { song : Api.Song
    , peaks : List ( Float, Float )
    , loop : Maybe Api.LoopRegion
    , separating : Bool
    , progress : Maybe Float
    , onSeparate : Bool -> msg
    , onMixer : msg
    , onBack : msg
    }
    -> Html msg
view config =
    div [ class "song-view" ]
        [ button [ class "back", onClick config.onBack ] [ text "← Library" ]
        , h2 [] [ text config.song.title ]
        , p [ class "dim" ] [ text (subtitle config.song) ]
        , Waveform.view
            { peaks = config.peaks
            , width = 960
            , height = 140
            , durationS = config.song.durationS
            , loop = Maybe.map (\region -> { startS = region.startS, endS = region.endS }) config.loop
            }
        , loopLine config.loop
        , separationPanel config
        , mixerPanel config
        ]


{-| What the shaded region on the waveform is, in words. The region is the part
of the song every one of the next several hundred repetitions is made of, which
is worth stating plainly rather than leaving as an unexplained rectangle.
-}
loopLine : Maybe Api.LoopRegion -> Html msg
loopLine loop =
    case loop of
        Nothing ->
            text ""

        Just region ->
            p [ class "dim" ]
                [ text
                    ("Loop "
                        ++ clock region.startS
                        ++ " – "
                        ++ clock region.endS
                        ++ " · "
                        ++ String.fromInt (round (region.endS - region.startS))
                        ++ " s · "
                        ++ String.fromInt (round region.tempo)
                        ++ " BPM"
                    )
                ]


clock : Float -> String
clock seconds =
    let
        total =
            round seconds
    in
    String.fromInt (total // 60)
        ++ ":"
        ++ String.padLeft 2 '0' (String.fromInt (modBy 60 total))


{-| The way into the mixer, and — when there is no way in — why.

Gated on the song actually having stems rather than on a status, because the
mixer's rows *are* the stems: with none there is nothing to put in it, and the
first preview would sit inside the per-song lock running Demucs with no
progress to report. Separation has a progress bar of its own two lines up;
this sends you to it instead of hiding the same wait behind a different label.
-}
mixerPanel :
    { a | song : Api.Song, separating : Bool, onMixer : msg }
    -> Html msg
mixerPanel config =
    let
        hasStems =
            not (List.isEmpty config.song.stems)

        running =
            config.separating || config.song.separationStatus == Api.Separating

        reason =
            if not hasStems then
                Just "Separate this song first — the mixer is built out of its stems."

            else if running then
                -- A separation finishing throws away the warm session and can
                -- change the stem list underneath an open mixer, so the door
                -- stays shut until it has. Read from the server's status as
                -- well as our own flag: a reload mid-separation forgets the
                -- flag but not the status.
                Just "The mixer opens once this separation finishes."

            else
                Nothing
    in
    div [ class "mixer-entry" ]
        [ button [ onClick config.onMixer, disabled (reason /= Nothing) ]
            [ text "Open the mixer" ]
        , case reason of
            Just words ->
                p [ class "dim" ] [ text words ]

            Nothing ->
                text ""
        ]


subtitle : Api.Song -> String
subtitle s =
    let
        minutes =
            round s.durationS // 60

        seconds =
            modBy 60 (round s.durationS)
    in
    String.fromInt minutes
        ++ ":"
        ++ String.padLeft 2 '0' (String.fromInt seconds)
        ++ " · "
        ++ String.fromInt s.sampleRate
        ++ " Hz"


separationPanel :
    { a
        | song : Api.Song
        , separating : Bool
        , progress : Maybe Float
        , onSeparate : Bool -> msg
    }
    -> Html msg
separationPanel config =
    let
        status =
            config.song.separationStatus
    in
    div [ class "separation" ]
        [ p [] [ text (Api.statusLabel status) ]
        , reasonFor status
        , stemList config.song.stems
        , progressBar config.progress
        , button
            [ onClick (config.onSeparate (needsForce status))
            , disabled config.separating
            ]
            [ text (buttonLabel status config.separating) ]
        ]


reasonFor : Api.SeparationStatus -> Html msg
reasonFor status =
    case status of
        Api.Fallback reason ->
            p [ class "error" ] [ text reason ]

        Api.SeparationFailed reason ->
            p [ class "error" ] [ text reason ]

        _ ->
            text ""


stemList : List String -> Html msg
stemList stems =
    if List.isEmpty stems then
        text ""

    else
        p [ class "dim" ] [ text (String.join " · " stems) ]


{-| A track with a fill inside it, rather than a bare fill: the fill carries
nothing but an inline `width`, so it needs a sibling-free parent of a known
size to be a percentage *of*, and the track is what shows the remainder.

Separation currently reports two progress points — 0.0 when it starts and 1.0
when it finishes, which is terminal and clears the bar — so in practice this
sits empty for the whole run. That is the payload being thin, not the bar
being broken; see `docs/project-state.md`.
-}
progressBar : Maybe Float -> Html msg
progressBar progress =
    case progress of
        Nothing ->
            text ""

        Just fraction ->
            div [ class "progress" ]
                [ div [ class "progress-track" ]
                    [ div
                        [ class "progress-fill"
                        , Html.Attributes.style "width"
                            (String.fromFloat (fraction * 100) ++ "%")
                        ]
                        []
                    ]
                , span [ class "dim" ]
                    [ text (String.fromInt (round (fraction * 100)) ++ "%") ]
                ]


{-| A cached fallback is sticky: the separation cache key says nothing about
whether Demucs was importable, so re-running without force returns the same
fallback forever. Offering a plain "Separate" there would do nothing visible.
-}
needsForce : Api.SeparationStatus -> Bool
needsForce status =
    case status of
        Api.Fallback _ ->
            True

        Api.SeparationFailed _ ->
            True

        _ ->
            False


buttonLabel : Api.SeparationStatus -> Bool -> String
buttonLabel status separating =
    if separating then
        "Separating…"

    else
        case status of
            Api.NotSeparated ->
                "Separate"

            Api.Separating ->
                "Separating…"

            Api.Separated ->
                "Separate again"

            Api.Fallback _ ->
                "Retry with Demucs"

            Api.SeparationFailed _ ->
                "Try again"
