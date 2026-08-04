module LibraryTest exposing (suite)

import Api
import Expect
import Page.Library as Library
import Test exposing (Test, describe, test)


aSong : String -> String -> Api.SeparationStatus -> Api.Song
aSong id title status =
    { id = id
    , path = "/music/" ++ id ++ ".flac"
    , title = title
    , durationS = 100.0
    , sampleRate = 44100
    , separationStatus = status
    , stems = []
    , addedAt = "2026-08-04T10:00:00+00:00"
    }


suite : Test
suite =
    describe "Page.Library"
        [ test "an empty library is distinguishable from one still loading" <|
            \_ ->
                Expect.notEqual
                    (Library.summary Library.Loading)
                    (Library.summary (Library.Loaded []))
        , test "summarises how many songs there are" <|
            \_ ->
                Expect.equal "2 songs"
                    (Library.summary
                        (Library.Loaded
                            [ aSong "a" "A" Api.Separated
                            , aSong "b" "B" Api.NotSeparated
                            ]
                        )
                    )
        , test "one song is not pluralised" <|
            \_ ->
                Expect.equal "1 song"
                    (Library.summary (Library.Loaded [ aSong "a" "A" Api.Separated ]))
        , test "a failed load explains itself" <|
            \_ ->
                Expect.equal "Could not load the library — could not reach the server"
                    (Library.summary (Library.Failed "could not reach the server"))
        ]
