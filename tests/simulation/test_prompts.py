from datetime import date

from yaksha.domain.languages import Language
from yaksha.domain.personas import PersonaConfig
from yaksha.domain.voices import VoiceGender, VoiceProvider, VoiceSettings
from yaksha.simulation.languages import HINDI_FORMS
from yaksha.simulation.prompts import caller_instructions

VOICE = VoiceSettings(provider=VoiceProvider.ELEVENLABS, id="v1")


def persona(language: Language, gender: VoiceGender | None) -> PersonaConfig:
    return PersonaConfig(
        prompt="You are calm.", language=language, voice=VOICE, voice_gender=gender
    )


def instructions(persona: PersonaConfig) -> str:
    return caller_instructions(
        persona, goal="Pay a bill.", known_facts=[], unknown_facts=[], today=date(2026, 9, 29)
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
