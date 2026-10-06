"""How a persona speaks each language: the prompt line, the first words, the idle nudge and the
sentence a voice preview speaks. Provider codes belong to the caller and the integrations, not
here."""

from dataclasses import dataclass

from yaksha.domain.languages import Language
from yaksha.domain.voices import VoiceGender


@dataclass(frozen=True)
class LanguagePolicy:
    instruction: str
    first_words: str
    """What the caller says first when it speaks first and the scenario sets none."""
    nudge: str
    sample: str
    goodbye: str
    """What the caller says when it has answered its most agent turns, or when it tries a second
    time to end the call without a word."""


LANGUAGES: dict[Language, LanguagePolicy] = {
    Language.EN: LanguagePolicy(
        instruction="Speak English.",
        first_words="Hello",
        nudge="Hello? Are you still there?",
        sample="Hi, I'm calling about my booking for next Tuesday. Can you check it for me?",
        goodbye="Okay, thanks. I have to go now. Bye.",
    ),
    Language.HINGLISH: LanguagePolicy(
        instruction="Speak Hinglish: Devanagari script, with common English words such as "
        "appointment or confirm kept in English.",
        first_words="Hello",
        nudge="हेलो? आप वहाँ हैं?",
        sample="नमस्ते, मुझे next Tuesday की booking के बारे में बात करनी है। क्या आप check कर सकते हैं?",
        goodbye="ठीक है, thank you. मुझे अब जाना होगा, bye.",
    ),
}

HINDI_FORMS: dict[VoiceGender, str] = {
    VoiceGender.MALE: (
        "When a verb is about yourself, use its masculine form (रहा, गया, था, सकता, चाहता); "
        "other words still agree with their own noun."
    ),
    VoiceGender.FEMALE: (
        "When a verb is about yourself, use its feminine form (रही, गई, थी, सकती, चाहती); "
        "other words still agree with their own noun."
    ),
}


def gender_line(language: Language, gender: VoiceGender | None) -> str | None:
    """Hindi verbs agree with the speaker, so the caller's forms follow its voice."""
    if language is Language.EN or gender is None:
        return None
    return HINDI_FORMS.get(gender)
