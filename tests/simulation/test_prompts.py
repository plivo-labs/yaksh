from truman.domain.personas import Language, PersonaConfig, Voice, VoiceGender, VoiceProvider
from truman.simulation.prompts import caller_instructions

VOICE = Voice(provider=VoiceProvider.ELEVENLABS, id="v1")


def persona(language: Language, gender: VoiceGender | None) -> PersonaConfig:
    return PersonaConfig(
        prompt="You are calm.", language=language, voice=VOICE, voice_gender=gender
    )


def test_hindi_speakers_use_the_grammatical_forms_of_their_voice() -> None:
    male_hindi = caller_instructions(persona(Language.HINGLISH, VoiceGender.MALE), "Pay a bill.")
    female_hindi = caller_instructions(
        persona(Language.HINGLISH, VoiceGender.FEMALE), "Pay a bill."
    )
    english = caller_instructions(persona(Language.EN, VoiceGender.MALE), "Pay a bill.")
    neutral = caller_instructions(persona(Language.HINGLISH, VoiceGender.NEUTRAL), "Pay a bill.")

    assert "मैं जा रहा हूँ" in male_hindi and "रही" not in male_hindi
    assert "मैं जा रही हूँ" in female_hindi
    assert "Hindi forms" not in english and "Hindi forms" not in neutral
