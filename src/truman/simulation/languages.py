"""How a persona speaks each language: the prompt line, the idle nudge and the sentence a
voice preview speaks. Provider codes belong to the caller and the integrations, not here."""

from dataclasses import dataclass

from truman.domain.languages import Language
from truman.domain.voices import VoiceGender


@dataclass(frozen=True)
class LanguagePolicy:
    instruction: str
    nudge: str
    sample: str
    pickup: str
    """What a person says on answering the phone."""
    goodbye: str
    """What the caller says when it has answered its most agent turns, or when it tries a second
    time to end the call without a word."""


LANGUAGES: dict[Language, LanguagePolicy] = {
    Language.EN: LanguagePolicy(
        "Speak English.",
        "Hello? Are you still there?",
        "Hi, I'm calling about my booking for next Tuesday. Can you check it for me?",
        "Hello?",
        "Okay, thanks. I have to go now. Bye.",
    ),
    Language.HINGLISH: LanguagePolicy(
        "Speak Hinglish: Devanagari script, with common English words such as appointment or "
        "confirm kept in English.",
        "हेलो? आप वहाँ हैं?",
        "नमस्ते, मुझे next Tuesday की booking के बारे में बात करनी है। क्या आप check कर सकते हैं?",
        "हेलो?",
        "ठीक है, thank you. मुझे अब जाना होगा, bye.",
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
