module SongTest exposing (suite)

{-| `Page.Song`'s two decisions: whether re-running separation needs `force`,
and what the button says. Both are read straight off a `SeparationStatus`, and
both are wrong in a way nobody would notice from a passing suite — a button
offering "Separate" on a cached fallback does nothing visible when clicked.

Views are not tested here; these are the pure functions the view reads from.
-}

import Api
import Expect
import Page.Song
import Test exposing (Test, describe, test)


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
        ]
