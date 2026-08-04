module Page.Library exposing (State(..), summary, view)

{-| The library: everything you have imported.

``State`` is a union rather than a record of flags because "loading", "loaded
but empty" and "failed" are genuinely different things to show, and a boolean
pair would let the impossible fourth combination exist.
-}

import Api
import Html exposing (Html, button, div, input, li, p, span, text, ul)
import Html.Attributes exposing (class, disabled, placeholder, value)
import Html.Events exposing (onClick, onInput)


type State
    = Loading
    | Loaded (List Api.Song)
    | Failed String


summary : State -> String
summary state =
    case state of
        Loading ->
            "Loading your library…"

        Loaded [] ->
            "Nothing imported yet."

        Loaded songs ->
            case List.length songs of
                1 ->
                    "1 song"

                n ->
                    String.fromInt n ++ " songs"

        Failed reason ->
            "Could not load the library — " ++ reason


view :
    { state : State
    , pathInput : String
    , importing : Bool
    , onPathInput : String -> msg
    , onImport : msg
    , onSelect : String -> msg
    }
    -> Html msg
view config =
    div [ class "library" ]
        [ p [ class "dim" ] [ text (summary config.state) ]
        , div [ class "import" ]
            [ input
                [ placeholder "/path/to/song.flac"
                , value config.pathInput
                , onInput config.onPathInput
                ]
                []
            , button
                [ onClick config.onImport
                , disabled (config.importing || String.isEmpty config.pathInput)
                ]
                [ text
                    (if config.importing then
                        "Importing…"

                     else
                        "Import"
                    )
                ]
            ]
        , case config.state of
            Loaded songs ->
                ul [ class "songs" ] (List.map (songRow config.onSelect) songs)

            _ ->
                text ""
        ]


songRow : (String -> msg) -> Api.Song -> Html msg
songRow onSelect s =
    li [ class "song", onClick (onSelect s.id) ]
        [ span [ class "title" ] [ text s.title ]
        , span [ class "dim" ] [ text (duration s.durationS) ]
        , span [ class "dim" ] [ text (Api.statusLabel s.separationStatus) ]
        ]


duration : Float -> String
duration seconds =
    let
        total =
            round seconds

        minutes =
            total // 60

        remainder =
            modBy 60 total
    in
    String.fromInt minutes
        ++ ":"
        ++ String.padLeft 2 '0' (String.fromInt remainder)
