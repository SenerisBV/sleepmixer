module WarnTest exposing (suite)

{-| The one thing said before a long job starts.

`Warn.forSource` is the whole of a decision that is otherwise made twice — the
mixer's Render button and the song screen's Separate button both ask it — so
what these tests defend is that it says *this* file's length and *this*
project's constraint, rather than a fixed sentence that would read the same for
a three-minute track.

The 4188-second case is the real file: seventy minutes imported by accident,
which is the incident the threshold exists to catch.

-}

import Expect
import Test exposing (Test, describe, test)
import Warn


{-| The sentence, or a failure that says which case produced no sentence.
-}
messageFor : Float -> (String -> Expect.Expectation) -> Expect.Expectation
messageFor seconds expect =
    case Warn.forSource seconds of
        Warn.Long message ->
            expect message

        Warn.NoWarning ->
            Expect.fail
                (String.fromFloat seconds ++ " s of source audio must warn")


contains : String -> String -> Expect.Expectation
contains needle haystack =
    if String.contains needle haystack then
        Expect.pass

    else
        Expect.fail ("expected \"" ++ needle ++ "\" in: " ++ haystack)


suite : Test
suite =
    describe "Warn.forSource"
        [ test "an ordinary track says nothing" <|
            \_ -> Expect.equal Warn.NoWarning (Warn.forSource 245)
        , test "a track just under the threshold says nothing" <|
            \_ -> Expect.equal Warn.NoWarning (Warn.forSource 899)
        , test "nor does one exactly at it" <|
            -- Fifteen minutes is the threshold, and the warning is for what is
            -- *over* it. Stated because a `>=` here would warn about a file the
            -- rule says nothing about, and nothing else in the suite would
            -- notice one second's difference.
            \_ -> Expect.equal Warn.NoWarning (Warn.forSource 900)
        , test "a second past it does warn" <|
            -- And still reads "15 minutes", because the length is rounded to
            -- the nearest minute and this file is fifteen and a bit. The
            -- sentence says "roughly" for exactly this reason: it is a
            -- magnitude, not a measurement, and a ceiling here would call a
            -- 15-minute-and-one-second file sixteen minutes.
            \_ -> messageFor 901 (contains "15")
        , test "a track over the threshold warns, and names its length" <|
            -- The real file. The plan's own version of this test also asserted
            -- the message contained "one" or "1 ", which is vacuous: "one
            -- worker" is in the fixed half of every sentence this can return,
            -- so that half passed against any implementation at all. The
            -- single-worker claim is checked properly below, against a
            -- different length, where a stub would have to say it too.
            \_ ->
                messageFor 4188
                    (\m -> Expect.equal True (String.contains "69" m || String.contains "70" m))
        , describe "what the sentence has to carry"
            -- Both halves, because a warning that says only "this is long" does
            -- not explain why it matters, and one that says only "there is one
            -- worker" does not say what set it off. A fixed sentence would pass
            -- one of these and fail the other.
            [ test "this file's own length, not a fixed number" <|
                \_ -> messageFor 1800 (contains "30")
            , test "and a different file's" <|
                \_ -> messageFor 3600 (contains "60")
            , test "that one worker runs everything" <|
                \_ -> messageFor 1800 (contains "worker")
            , test "so anything behind it waits" <|
                \_ -> messageFor 1800 (contains "wait")
            ]
        , describe "the edges"
            [ test "a song of no length says nothing" <|
                \_ -> Expect.equal Warn.NoWarning (Warn.forSource 0)
            , test "and neither does a nonsense negative one" <|
                -- `duration_s` comes off a decoded file and is never negative;
                -- what matters is that the absurd case falls to silence rather
                -- than to a warning about a track of minus one minutes.
                \_ -> Expect.equal Warn.NoWarning (Warn.forSource -60)
            ]
        ]
