module Page.Song exposing (view)

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
    , separating : Bool
    , progress : Maybe Float
    , onSeparate : Bool -> msg
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
            , loop = Nothing
            }
        , separationPanel config
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


progressBar : Maybe Float -> Html msg
progressBar progress =
    case progress of
        Nothing ->
            text ""

        Just fraction ->
            div [ class "progress" ]
                [ div
                    [ class "progress-fill"
                    , Html.Attributes.style "width"
                        (String.fromFloat (fraction * 100) ++ "%")
                    ]
                    []
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
