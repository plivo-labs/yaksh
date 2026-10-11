from datetime import date

import pytest

from yaksha.domain.languages import Language
from yaksha.domain.personas import PersonaConfig
from yaksha.domain.voices import VoiceGender, VoiceProvider, VoiceSettings
from yaksha.simulation.languages import HINDI_FORMS, LANGUAGES, SPANISH_FORMS, SPEAKER_FORMS
from yaksha.simulation.prompts import caller_instructions

VOICE = VoiceSettings(provider=VoiceProvider.ELEVENLABS, id="v1")


def persona(language: Language, gender: VoiceGender | None) -> PersonaConfig:
    return PersonaConfig(
        prompt="You are calm.", language=language, voice=VOICE, voice_gender=gender
    )


def instructions(persona: PersonaConfig) -> str:
    return caller_instructions(
        persona,
        instructions="Pay a bill.",
        known_facts=[],
        unknown_facts=[],
        today=date(2026, 9, 29),
    )


def test_hindi_speakers_use_the_grammatical_forms_of_their_voice() -> None:
    male_hindi = instructions(persona(Language.HI, VoiceGender.MALE))
    female_hindi = instructions(persona(Language.HI, VoiceGender.FEMALE))
    english = instructions(persona(Language.EN, VoiceGender.MALE))
    neutral = instructions(persona(Language.HI, VoiceGender.NEUTRAL))

    male, female = HINDI_FORMS[VoiceGender.MALE], HINDI_FORMS[VoiceGender.FEMALE]
    assert male in male_hindi and female not in male_hindi
    assert female in female_hindi and male not in female_hindi
    assert all(line not in text for line in (male, female) for text in (english, neutral))


def test_other_languages_whose_words_agree_with_the_speaker_get_their_own_forms() -> None:
    female_marathi = instructions(persona(Language.MR, VoiceGender.FEMALE))
    male_gujarati = instructions(persona(Language.GU, VoiceGender.MALE))
    female_spanish = instructions(persona(Language.ES, VoiceGender.FEMALE))
    tamil = instructions(persona(Language.TA, VoiceGender.FEMALE))

    assert SPEAKER_FORMS[VoiceGender.FEMALE] in female_marathi
    assert SPEAKER_FORMS[VoiceGender.MALE] in male_gujarati
    assert SPANISH_FORMS[VoiceGender.FEMALE] in female_spanish
    assert all(form not in female_marathi for form in HINDI_FORMS.values())
    assert all(form not in tamil for form in (*SPEAKER_FORMS.values(), *HINDI_FORMS.values()))


@pytest.mark.parametrize("language", list(Language))
def test_every_language_tells_the_caller_how_to_speak_it(language: Language) -> None:
    assert LANGUAGES[language].instruction in instructions(persona(language, VoiceGender.FEMALE))
