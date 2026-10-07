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
        self._models: dict[str, tuple[tuple[object, ...], JsonModel | None]] = {}
        """Each model by its use, with the settings it was built from."""
        self._replaced: list[JsonModel] = []
        """Models replaced by new settings; a request may still use one, so they are closed at
        shutdown."""

    def voice_clients(self, settings: AppSettings) -> VoiceClients:
        key = reveal(settings.secrets.elevenlabs_api_key)
        if key != self._voice_key:
            self._voice_key = key
            self._voice_clients = (
                {} if key is None else {VoiceProvider.ELEVENLABS: ElevenLabsClient(key)}
            )
        return self._voice_clients

    def generation_model(self, settings: AppSettings) -> JsonModel | None:
        """The model that writes scenarios; None while no LLM provider key is saved."""
        generation = settings.generation
        return self._model(
            "generation",
            settings,
            settings.generation_model,
            generation.timeout_s,
            generation.reasoning_effort,
        )

    def brief_model(self, settings: AppSettings) -> JsonModel | None:
        """A fast model that drafts an agent's brief while the person waits."""
        brief = settings.brief
        return self._model("brief", settings, brief.model, brief.timeout_s, brief.reasoning_effort)

    def _model(
        self,
        use: str,
        settings: AppSettings,
        model: str,
        timeout_s: float,
        reasoning_effort: str | None,
    ) -> JsonModel | None:
        key = reveal(settings.secrets.llm_api_key)
        inputs = (settings.llm.base_url, key, model, timeout_s, reasoning_effort)
        cached = self._models.get(use)
        if cached is not None and cached[0] == inputs:
            return cached[1]
        if cached is not None and cached[1] is not None:
            self._replaced.append(cached[1])
        built = (
            None
            if key is None
            else OpenAIJsonModel.openai(
                key,
                model,
                base_url=settings.llm.base_url,
                timeout_s=timeout_s,
                reasoning_effort=reasoning_effort,
            )
        )
        self._models[use] = (inputs, built)
        return built

    async def close(self) -> None:
        for model in (*self._replaced, *(built for _, built in self._models.values())):
            if model is not None:
                await model.close()
