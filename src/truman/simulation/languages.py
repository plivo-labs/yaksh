"""How a persona speaks each language: the prompt line and the idle nudge. Provider codes
belong to the caller and the integrations, not here."""

from dataclasses import dataclass

from truman.domain.personas import Language, VoiceGender


@dataclass(frozen=True)
class LanguagePolicy:
    instruction: str
    nudge: str


ENGLISH_NUDGE = "Hello? Are you still there?"
HINDI_NUDGE = "हेलो? आप वहाँ हैं?"

LANGUAGES: dict[Language, LanguagePolicy] = {
    Language.EN: LanguagePolicy("Speak English.", ENGLISH_NUDGE),
    Language.HI: LanguagePolicy("Speak Hindi in Devanagari script.", HINDI_NUDGE),
    Language.HINGLISH: LanguagePolicy(
        "Speak Hinglish: Devanagari script, with common English words kept in English. "
        'Example: "मेरा appointment confirm हो गया है।"',
        HINDI_NUDGE,
    ),
    Language.EN_HI: LanguagePolicy(
        "You speak English and Hindi. Use the language the agent uses. "
        "Write Hindi in Devanagari script.",
        ENGLISH_NUDGE,
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
