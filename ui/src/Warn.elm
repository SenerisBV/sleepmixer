module Warn exposing (Warning(..), forSource)

{-| What to say before starting something long, and when to say it.

One module rather than a sentence written twice, because two screens ask the
same question about the same constraint: the mixer's Render button and the song
screen's Separate button both put work on the one worker that runs everything.
Two copies would drift, and the day they disagreed the interface would be
stating two different rules about a queue that has only one.

**It warns; it does not block.** A long file is a legitimate thing to render —
the threshold is here to catch the accident, not to have an opinion about long
songs. Nothing here disables a button or refuses a request.

-}


type Warning
    = NoWarning
    | Long String


{-| Fifteen minutes of source audio.

A judgement rather than a measurement, and worth naming as one: it is roughly
three times the longest track anyone would normally feed this, so an ordinary
album cut is nowhere near it and the file that caused the original incident —
seventy minutes, imported by accident, with no way to get at it except killing
the server from a terminal — is nowhere near it either, from the other side.

There is no cost model behind the number, and one measurement does not make
one. What has been measured is a single render — a 246.6 s source to a
20-minute mix in 13.6 s once its stems were cached — which says the expensive
term is separation rather than output length, and so says this warning is at
least watching the right *number*. It says nothing about where the threshold
should sit: nothing has been timed cold, or on a long source, or on other
hardware. Picking a threshold that *looked* derived from one warm run would be
inventing precision the same way a fabricated time estimate would.
See `docs/project-state.md` for the case this warning still misses.
-}
thresholdS : Float
thresholdS =
    15 * 60


{-| Whether a job on this much source audio is worth warning about.
-}
forSource : Float -> Warning
forSource durationS =
    if durationS <= thresholdS then
        NoWarning

    else
        Long (sentence durationS)


{-| Both facts, because either one alone is half an explanation.

The length is what set the warning off, and without it the sentence is a
standing notice rather than something about the file in front of you. The one
worker is *why* the length matters: a long job here does not run slowly
alongside the others, it stops them — which is the shape of the original
incident, where a seventy-minute file imported by accident blocked the small
one the operator actually wanted to test.

"Roughly" is doing real work: the length is rounded to the nearest minute, so a
file a second over the threshold reads as fifteen minutes. Saying "roughly"
costs a word and keeps the readout from claiming a precision it does not have.
-}
sentence : Float -> String
sentence durationS =
    "This is roughly "
        ++ String.fromInt (round (durationS / 60))
        ++ " minutes of audio, and everything here runs on one worker — so "
        ++ "anything you start behind it waits until it has finished."
