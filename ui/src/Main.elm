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

import Browser
import Html exposing (Html, div, h1, p, text)
import Html.Attributes exposing (class)
import Http
import Json.Decode as Decode


type alias Model =
    { health : Health }


type Health
    = Checking
    | Ready String
    | Unreachable String


type Msg
    = GotHealth (Result Http.Error String)


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
    ( { health = Checking }
    , Http.get
        { url = "/api/health"
        , expect = Http.expectJson GotHealth (Decode.field "version" Decode.string)
        }
    )


update : Msg -> Model -> ( Model, Cmd Msg )
update msg model =
    case msg of
        GotHealth (Ok version) ->
            ( { model | health = Ready version }, Cmd.none )

        GotHealth (Err err) ->
            ( { model | health = Unreachable (httpErrorToString err) }, Cmd.none )


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
                p [] [ text ("Connected to sleepmix " ++ version ++ ".") ]

            Unreachable reason ->
                p [ class "error" ] [ text ("Not connected — " ++ reason) ]
        ]
