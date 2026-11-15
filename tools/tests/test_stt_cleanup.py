"""Transcript clean-up: a whisper-thin decode is put back into the radio's real words, and the words come out
as the commands and the spoken-number parser expect them."""
from _common import check, done, load

sc = load()
fb = sc.stt_fallback

check(fb("Box this lap and put the fuel map on foreplays.") == "box this lap and put the fuel map on for please.",
      "foreplays -> for please")
check(fb("Box this lap and put the fuel map on cleaves.").endswith("for please.") or
      "please." in fb("Box this lap and put the fuel map on cleaves."), "cleaves -> please")
check("do you read me" in fb("Radio check, radio check, see you easily."), "see you easily -> do you read me")
check(fb("Push push push where am I losing time, Inspector Two?") ==
      "Push push push where am I losing time, in sector two?", "Inspector Two -> in sector two")
check(fb("Put the coats to apex and turn the braking cones on.") ==
      "Put the coach to apex and turn the braking tones on.", "coats/cone -> coach/tone")
check(fb("How is my braking in two times brake?") == "How is my braking in into turn three?",
      "two times brake -> into turn three")
check(fb("How is my braking into tank brake?") == "How is my braking into turn three?",
      "into tank brake -> into turn three (no doubled 'into')")
check("the rear is stepping" in fb("The wheel is stepping out").lower(), "wheel is stepping -> rear is stepping")
check("apex" in fb("Switch the coach to apex and turn the braking tones on."),
      "a correct decode keeps its words")

check(fb("Box the braking point.") == "Box the braking point.",
      "a word that is real English is left alone (apex stays, so does box)")
check(fb("How is my lap time?") == "How is my lap time?", "question words are untouched")

# tidy_speech: spoken nouns keep the parser's words, and Whisper's repetition is dropped
check(sc.tidy_speech("into turn 3 please") == "Into turn three please", "digits after turn become words")
check(sc.tidy_speech("where am I losing time in sector 2") == "Where am I losing time in sector two",
      "digits after sector become words")
check(sc.tidy_speech("3 laps") == "3 laps", "a bare number that is not a radio noun stays a digit")
check(sc.tidy_speech("radio check. radio check. do you read me") == "Radio check. do you read me",
      "the repeated half is dropped")
check(sc.tidy_speech("um, box this lap") == "Box this lap", "a leading filler goes")

# what the command parser makes of the cleaned text
conv = sc.Conversation.__new__(sc.Conversation)
for said, want in (("Box this lap and put the fuel map on four please.", True),
                   ("Radio check, radio check, do you read me?", True),
                   ("Switch the coach to apex", True),
                   ("Where am I losing time in sector two?", False)):
    hit = any(rx.search(said.lower()) for rx in (conv._RE_PIT, conv._RE_RADIO, conv._RE_PERSONA_SWITCH))
    check(hit is want, f"command regexes see {said!r} as {want}")
done()
