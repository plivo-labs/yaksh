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


LANGUAGES: dict[Language, LanguagePolicy] = {
    Language.EN: LanguagePolicy(
        "Speak English.",
        "Hello? Are you still there?",
        "Hi, I'm calling about my booking for next Tuesday. Can you check it for me?",
    ),
    Language.HINGLISH: LanguagePolicy(
        "Speak Hinglish: Devanagari script, with common English words kept in English. "
        'Example: "मेरा appointment confirm हो गया है।"',
        "हेलो? आप वहाँ हैं?",
        "नमस्ते, मुझे next Tuesday की booking के बारे में बात करनी है। क्या आप check कर सकते हैं?",
    ),
}

HINDI_FORMS: dict[VoiceGender, str] = {
    VoiceGender.MALE: "Refer to yourself with masculine Hindi forms, for example 'मैं जा रहा हूँ'.",
    VoiceGender.FEMALE: "Refer to yourself with feminine Hindi forms, for example 'मैं जा रही हूँ'.",
}


def gender_line(language: Language, gender: VoiceGender | None) -> str | None:
    """Hindi verbs agree with the speaker, so the caller's forms follow its voice."""
    if language is Language.EN or gender is None:
        return None
    return HINDI_FORMS.get(gender)
