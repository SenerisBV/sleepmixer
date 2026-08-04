module Main exposing (main)

{-| The sleepmix interface.

Elm rather than a JavaScript framework because most of this is written by an
agent, and the compiler turns a whole class of mistakes — a renamed field, an
unhandled case — into build failures rather than into something that renders
blank and says nothing.

Where Elm stops: ports are asynchronous and JSON-only, so the Web Audio engine
and the EventSource connection live in hand-written JavaScript. Elm sends
parameters out and receives outcomes back; it never touches audio bytes.
-}

import Api
import Browser
import Html exposing (Html, div, h1, p, text)
import Html.Attributes exposing (class)
import Http
import Json.Decode as Decode
import Page.Library as Library
import Request


type alias Model =
    { health : Health
    , library : Library.State
    , pathInput : String
    , importing : Bool
    , importError : Maybe String
    , selectedSongId : Maybe String
    }


type Health
    = Checking
    | Ready String
    | Unreachable String


type Msg
    = GotHealth (Result Http.Error String)
    | GotSongs (Result Http.Error (List Api.Song))
    | PathChanged String
    | ImportClicked
    | Imported (Result Http.Error Api.Song)
    | SelectedSong String


main : Program () Model Msg
main =
    Browser.element
        { init = init
        , update = update
        , subscriptions = always Sub.none
        , view = view
        }


init : () -> ( Model, Cmd Msg )
init _ =
    ( { health = Checking
      , library = Library.Loading
      , pathInput = ""
      , importing = False
      , importError = Nothing
      , selectedSongId = Nothing
      }
    , Cmd.batch
        [ Http.get
            { url = "/api/health"
            , expect = Http.expectJson GotHealth (Decode.field "version" Decode.string)
            }
        , Request.songs GotSongs
        ]
    )


update : Msg -> Model -> ( Model, Cmd Msg )
update msg model =
    case msg of
        GotHealth (Ok version) ->
            ( { model | health = Ready version }, Cmd.none )

        GotHealth (Err err) ->
            ( { model | health = Unreachable (httpErrorToString err) }, Cmd.none )

        GotSongs (Ok songs) ->
            ( { model | library = Library.Loaded songs }, Cmd.none )

        GotSongs (Err err) ->
            ( { model | library = Library.Failed (httpErrorToString err) }, Cmd.none )

        PathChanged path ->
            ( { model | pathInput = path }, Cmd.none )

        ImportClicked ->
            if model.importing || String.isEmpty model.pathInput then
                ( model, Cmd.none )

            else
                ( { model | importing = True, importError = Nothing }
                , Request.importSong model.pathInput Imported
                )

        Imported (Ok _) ->
            -- Re-fetch rather than append the returned song: the server
            -- deduplicates by path, so importing a file that is already in
            -- the library returns the existing row, and appending it here
            -- would show that song twice.
            ( { model | importing = False, pathInput = "" }
            , Request.songs GotSongs
            )

        Imported (Err err) ->
            ( { model | importing = False, importError = Just (httpErrorToString err) }
            , Cmd.none
            )

        SelectedSong songId ->
            ( { model | selectedSongId = Just songId }, Cmd.none )


httpErrorToString : Http.Error -> String
httpErrorToString err =
    case err of
        Http.BadUrl url ->
            "bad url: " ++ url

        Http.Timeout ->
            "the server took too long to answer"

        Http.NetworkError ->
            "could not reach the server"

        Http.BadStatus code ->
            "the server answered " ++ String.fromInt code

        Http.BadBody detail ->
            "could not read the server's answer: " ++ detail


view : Model -> Html Msg
view model =
    div [ class "app" ]
        [ h1 [] [ text "sleepmix" ]
        , case model.health of
            Checking ->
                p [] [ text "Connecting…" ]

            Ready version ->
                p [ class "dim" ] [ text ("Connected to sleepmix " ++ version ++ ".") ]

            Unreachable reason ->
                p [ class "error" ] [ text ("Not connected — " ++ reason) ]
        , Library.view
            { state = model.library
            , pathInput = model.pathInput
            , importing = model.importing
            , onPathInput = PathChanged
            , onImport = ImportClicked
            , onSelect = SelectedSong
            }
        , case model.importError of
            Nothing ->
                text ""

            Just reason ->
                p [ class "error" ] [ text ("Could not import that file — " ++ reason) ]
        , case model.selectedSongId of
            Nothing ->
                text ""

            Just songId ->
                -- Placeholder: the song screen (waveform, stems, separation
                -- controls) is the next task. For now this only proves that
                -- a click on a library row reaches the model.
                p [ class "dim" ] [ text ("Selected song " ++ songId ++ " — song screen not built yet.") ]
        ]
