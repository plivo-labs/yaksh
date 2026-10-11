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


ENGLISH = LanguagePolicy(
    instruction="Speak English.",
    first_words="Hello",
    nudge="Hello? Are you still there?",
    sample="Hi, I'm calling about my booking for next Tuesday. Can you check it for me?",
    goodbye="Okay, thanks. I have to go now. Bye.",
)


def everyday(name: str, script: str, sample: str) -> LanguagePolicy:
    """A language that callers mix with English words. Its prompt line and preview sentence are
    its own; the lines the caller says as written are the English ones, as callers often say
    them."""
    return LanguagePolicy(
        instruction=f"Speak {name} the way people talk every day: {script} script, with common "
        "English words such as appointment or confirm kept in English.",
        first_words=ENGLISH.first_words,
        nudge=ENGLISH.nudge,
        sample=sample,
        goodbye=ENGLISH.goodbye,
    )


LANGUAGES: dict[Language, LanguagePolicy] = {
    Language.EN: ENGLISH,
    Language.HI: LanguagePolicy(
        instruction="Speak Hinglish: Devanagari script, with common English words such as "
        "appointment or confirm kept in English.",
        first_words="Hello",
        nudge="हेलो? आप वहाँ हैं?",
        sample="नमस्ते, मुझे next Tuesday की booking के बारे में बात करनी है। क्या आप check कर सकते हैं?",
        goodbye="ठीक है, thank you. मुझे अब जाना होगा, bye.",
    ),
    Language.BN: everyday(
        "Bengali",
        "Bengali",
        "নমস্কার, আমি next Tuesday-র booking নিয়ে কথা বলতে চাই। আপনি একটু check করে দেবেন?",
    ),
    Language.GU: everyday(
        "Gujarati",
        "Gujarati",
        "નમસ્તે, મારે next Tuesday ની booking વિશે વાત કરવી છે. તમે check કરી શકશો?",
    ),
    Language.KN: everyday(
        "Kannada",
        "Kannada",
        "ನಮಸ್ಕಾರ, ನನ್ನ next Tuesday booking ಬಗ್ಗೆ ಮಾತಾಡಬೇಕಿತ್ತು. ನೀವು ಸ್ವಲ್ಪ check ಮಾಡ್ತೀರಾ?",
    ),
    Language.MR: everyday(
        "Marathi",
        "Devanagari",
        "नमस्कार, मला next Tuesday च्या booking बद्दल बोलायचं आहे. तुम्ही check करू शकाल का?",
    ),
    Language.TA: everyday(
        "Tamil",
        "Tamil",
        "வணக்கம், என்னோட next Tuesday booking பத்தி பேசணும். கொஞ்சம் check பண்ணி சொல்ல முடியுமா?",
    ),
    Language.TE: everyday(
        "Telugu",
        "Telugu",
        "నమస్కారం, నా next Tuesday booking గురించి మాట్లాడాలి. మీరు కొంచెం check చేయగలరా?",
    ),
    Language.ES: LanguagePolicy(
        instruction="Speak Spanish the way people talk every day.",
        first_words=ENGLISH.first_words,
        nudge=ENGLISH.nudge,
        sample="Hola, llamo por mi reserva del próximo martes. ¿Me la puede revisar?",
        goodbye=ENGLISH.goodbye,
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


SPEAKER_FORMS: dict[VoiceGender, str] = {
    VoiceGender.MALE: (
        "When a verb is about yourself, use its masculine form; other words still agree with "
        "their own noun."
    ),
    VoiceGender.FEMALE: (
        "When a verb is about yourself, use its feminine form; other words still agree with "
        "their own noun."
    ),
}
SPANISH_FORMS: dict[VoiceGender, str] = {
    VoiceGender.MALE: (
        "When an adjective or participle is about yourself, use its masculine form (cansado, "
        "listo); other words still agree with their own noun."
    ),
    VoiceGender.FEMALE: (
        "When an adjective or participle is about yourself, use its feminine form (cansada, "
        "lista); other words still agree with their own noun."
    ),
}
FORMS: dict[Language, dict[VoiceGender, str]] = {
    Language.HI: HINDI_FORMS,
    Language.MR: SPEAKER_FORMS,
    Language.GU: SPEAKER_FORMS,
    Language.ES: SPANISH_FORMS,
}
"""The languages whose words agree with the speaker."""


def gender_line(language: Language, gender: VoiceGender | None) -> str | None:
    """Where words agree with the speaker, the caller's forms follow its voice."""
    if gender is None:
        return None
    return FORMS.get(language, {}).get(gender)
