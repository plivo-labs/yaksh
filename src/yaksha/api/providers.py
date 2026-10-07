"""The provider clients the API uses, built from the stored settings and built again when the
settings they depend on change."""

from yaksha.domain.language_models import JsonModel
from yaksha.domain.settings import AppSettings, reveal
from yaksha.domain.voices import VoiceProvider
from yaksha.integrations.elevenlabs import ElevenLabsClient
from yaksha.integrations.openai_models import OpenAIJsonModel
from yaksha.simulation.voices import VoiceClients


class Providers:
    def __init__(self) -> None:
        self._voice_key: str | None = None
        self._voice_clients: VoiceClients = {}
        self._generation_inputs: tuple[object, ...] | None = None
        self._generation_model: JsonModel | None = None
        self._replaced: list[JsonModel] = []
        """Models replaced by new settings; a generation may still use one, so they are
        closed at shutdown."""

    def voice_clients(self, settings: AppSettings) -> VoiceClients:
        key = reveal(settings.secrets.elevenlabs_api_key)
        if key != self._voice_key:
            self._voice_key = key
            self._voice_clients = (
                {} if key is None else {VoiceProvider.ELEVENLABS: ElevenLabsClient(key)}
            )
        return self._voice_clients

    def generation_model(self, settings: AppSettings) -> JsonModel | None:
        """The model that writes scenarios, at the LLM provider; None while no key is saved."""
        generation = settings.generation
        inputs = (
            settings.llm.base_url,
            reveal(settings.secrets.llm_api_key),
            settings.generation_model,
            generation,
        )
        if inputs == self._generation_inputs:
            return self._generation_model
        if self._generation_model is not None:
            self._replaced.append(self._generation_model)
        self._generation_inputs = inputs
        key = reveal(settings.secrets.llm_api_key)
        self._generation_model = (
            None
            if key is None
            else OpenAIJsonModel.openai(
                key,
                settings.generation_model,
                base_url=settings.llm.base_url,
                timeout_s=generation.timeout_s,
                reasoning_effort=generation.reasoning_effort,
            )
        )
        return self._generation_model

    async def close(self) -> None:
        for model in (*self._replaced, self._generation_model):
            if model is not None:
                await model.close()
