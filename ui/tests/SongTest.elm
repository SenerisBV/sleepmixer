module SongTest exposing (suite)

{-| `Page.Song`'s two decisions: whether re-running separation needs `force`,
and what the button says. Both are read straight off a `SeparationStatus`, and
both are wrong in a way nobody would notice from a passing suite — a button
offering "Separate" on a cached fallback does nothing visible when clicked.

Mostly pure functions, and then one thing that is not: the long-source warning
beside the Separate button is asserted against the *rendered* screen. A
`Warn.forSource` that is perfect and never called is a warning nobody sees, and
this suite could not have told the difference.
-}

import Api
import Expect
import Main
import Page.Song
import Test exposing (Test, describe, test)
import Test.Html.Query as Query
import Test.Html.Selector as Selector


song : Api.Song
song =
    { id = "song-1"
    , path = "/tmp/a.wav"
    , title = "A"
    , durationS = 245.0
    , sampleRate = 44100
    , separationStatus = Api.NotSeparated
    , stems = []
    , addedAt = "2026-08-05"
    }


{-| The song screen as the application actually draws it.

Through `Main.view` rather than `Page.Song.view` with a record written here, so
that this says something about the screen a user reaches rather than about a
function called in a test. No schema is needed: the song route does not use one.
-}
screen : Api.Song -> Query.Single Main.Msg
screen s =
    let
        fresh =
            Tuple.first (Main.init ())
    in
    { fresh | selectedSongId = Just s.id, currentSong = Just s }
        |> Main.view
        |> Query.fromHtml


suite : Test
suite =
    describe "Page.Song"
        [ describe "needsForce"
            [ test "a song that has never been separated does not" <|
                \_ -> Page.Song.needsForce Api.NotSeparated |> Expect.equal False
            , test "a song mid-separation does not" <|
                \_ -> Page.Song.needsForce Api.Separating |> Expect.equal False
            , test "a separated song re-separates plainly" <|
                \_ -> Page.Song.needsForce Api.Separated |> Expect.equal False
            , test "a cached fallback does, because the cache key ignores why" <|
                \_ ->
                    Page.Song.needsForce (Api.Fallback "no torch")
                        |> Expect.equal True
            , test "a failure does too" <|
                \_ ->
                    Page.Song.needsForce (Api.SeparationFailed "disk full")
                        |> Expect.equal True
            ]
        , describe "buttonLabel, while nothing is running"
            [ test "not separated" <|
                \_ ->
                    Page.Song.buttonLabel Api.NotSeparated False
                        |> Expect.equal "Separate"
            , test "separating" <|
                \_ ->
                    Page.Song.buttonLabel Api.Separating False
                        |> Expect.equal "Separating…"
            , test "separated" <|
                \_ ->
                    Page.Song.buttonLabel Api.Separated False
                        |> Expect.equal "Separate again"
            , test "a fallback offers the retry that would actually change it" <|
                \_ ->
                    Page.Song.buttonLabel (Api.Fallback "no torch") False
                        |> Expect.equal "Retry with Demucs"
            , test "a failure" <|
                \_ ->
                    Page.Song.buttonLabel (Api.SeparationFailed "disk full") False
                        |> Expect.equal "Try again"
            ]
        , describe "buttonLabel, while a separation is in flight"
            [ test "every status reads the same, because only one thing is true" <|
                \_ ->
                    [ Api.NotSeparated
                    , Api.Separating
                    , Api.Separated
                    , Api.Fallback "no torch"
                    , Api.SeparationFailed "disk full"
                    ]
                        |> List.map (\status -> Page.Song.buttonLabel status True)
                        |> Expect.equal (List.repeat 5 "Separating…")
            ]
        , describe "the long-source warning, as the screen renders it"
            -- Separation goes onto the same one worker a render does, so this
            -- is the same sentence out of the same module the mixer uses. What
            -- these defend is that it is on the screen at all: deleting the
            -- call leaves every `Warn` test green and the warning gone.
            [ test "a seventy-minute file is warned about, in minutes" <|
                \_ ->
                    screen { song | durationS = 4188 }
                        |> Query.find [ Selector.class "warn" ]
                        |> Query.has [ Selector.text "roughly 70 minutes" ]
            , test "and says why it matters, which is the one worker" <|
                \_ ->
                    screen { song | durationS = 4188 }
                        |> Query.find [ Selector.class "warn" ]
                        |> Query.has [ Selector.text "one worker" ]
            , test "an ordinary track is not warned about" <|
                \_ ->
                    screen song
                        |> Query.findAll [ Selector.class "warn" ]
                        |> Query.count (Expect.equal 0)
            ]
        ]
