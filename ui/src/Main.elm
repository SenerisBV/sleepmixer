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
import Page.Song
import Request


type alias Model =
    { health : Health
    , library : Library.State
    , pathInput : String
    , importing : Bool
    , importError : Maybe String
    , selectedSongId : Maybe String
    , currentSong : Maybe Api.Song
    , songError : Maybe String
    , peaks : List ( Float, Float )
    , peaksError : Maybe String
    , separating : Bool
    , separateError : Maybe String
    }


{-| Which screen is showing.

Not stored in the model directly — it is derived from `selectedSongId` by
`routeFor`, so there is exactly one source of truth for "which song, if any,
is open" rather than two things that could disagree.
-}
type Route
    = Library
    | SongView String


routeFor : Model -> Route
routeFor model =
    case model.selectedSongId of
        Nothing ->
            Library

        Just songId ->
            SongView songId


{-| How many peak buckets to ask for. 200 buckets across the 960px-wide
waveform in `Page.Song` gives a bar every ~4.8px, dense enough to show shape
without asking the server to compute (and the browser to draw) more detail
than a screen can show.
-}
peakBuckets : Int
peakBuckets =
    200


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
    | BackToLibrary
    | GotSongDetail String (Result Http.Error Api.Song)
    | GotPeaks String (Result Http.Error (List ( Float, Float )))
    | SeparateClicked Bool
    | Separated (Result Http.Error Api.Job)


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
      , currentSong = Nothing
      , songError = Nothing
      , peaks = []
      , peaksError = Nothing
      , separating = False
      , separateError = Nothing
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
            -- Entering a song resets everything the previous one left behind
            -- (peaks, errors, an in-flight separate) so stale state from one
            -- song can never bleed into the next.
            ( { model
                | selectedSongId = Just songId
                , currentSong = Nothing
                , songError = Nothing
                , peaks = []
                , peaksError = Nothing
                , separating = False
                , separateError = Nothing
              }
            , Cmd.batch
                [ Request.song songId (GotSongDetail songId)
                , Request.peaks songId peakBuckets (GotPeaks songId)
                ]
            )

        BackToLibrary ->
            ( { model | selectedSongId = Nothing }, Cmd.none )

        GotSongDetail songId result ->
            -- Guard against a slow response landing after the user has
            -- already navigated elsewhere.
            if model.selectedSongId /= Just songId then
                ( model, Cmd.none )

            else
                case result of
                    Ok song ->
                        ( { model | currentSong = Just song, songError = Nothing }, Cmd.none )

                    Err err ->
                        ( { model | songError = Just (httpErrorToString err) }, Cmd.none )

        GotPeaks songId result ->
            if model.selectedSongId /= Just songId then
                ( model, Cmd.none )

            else
                case result of
                    Ok peaks ->
                        ( { model | peaks = peaks, peaksError = Nothing }, Cmd.none )

                    Err err ->
                        ( { model | peaksError = Just (httpErrorToString err) }, Cmd.none )

        SeparateClicked force ->
            case model.selectedSongId of
                Nothing ->
                    ( model, Cmd.none )

                Just songId ->
                    ( { model | separating = True, separateError = Nothing }
                    , Request.startSeparation songId force Separated
                    )

        Separated (Ok _) ->
            -- Re-fetch rather than trust the job response: the job reports
            -- its own progress, not the song's separation_status, and that
            -- status is what the panel and the button label read from.
            case model.selectedSongId of
                Nothing ->
                    ( { model | separating = False }, Cmd.none )

                Just songId ->
                    ( { model | separating = False }
                    , Request.song songId (GotSongDetail songId)
                    )

        Separated (Err err) ->
            ( { model | separating = False, separateError = Just (httpErrorToString err) }
            , Cmd.none
            )


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
        , case routeFor model of
            Library ->
                libraryView model

            SongView songId ->
                songView model songId
        ]


libraryView : Model -> Html Msg
libraryView model =
    div []
        [ Library.view
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
        ]


{-| The song screen. `currentSong` is `Nothing` until its fetch lands — until
then this shows a loading line rather than the page, since `Page.Song.view`
needs a real `Api.Song` to read a title and duration from.
-}
songView : Model -> String -> Html Msg
songView model songId =
    case model.currentSong of
        Nothing ->
            case model.songError of
                Nothing ->
                    p [ class "dim" ] [ text "Loading song…" ]

                Just reason ->
                    p [ class "error" ] [ text ("Could not load that song — " ++ reason) ]

        Just song ->
            div []
                [ Page.Song.view
                    { song = song
                    , peaks = model.peaks
                    , separating = model.separating
                    , progress = Nothing
                    , onSeparate = SeparateClicked
                    , onBack = BackToLibrary
                    }
                , case model.peaksError of
                    Nothing ->
                        text ""

                    Just reason ->
                        p [ class "error" ] [ text ("Could not load the waveform — " ++ reason) ]
                , case model.separateError of
                    Nothing ->
                        text ""

                    Just reason ->
                        p [ class "error" ] [ text ("Could not start separation — " ++ reason) ]
                ]
