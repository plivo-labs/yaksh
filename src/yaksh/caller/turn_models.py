"""The VAD and end-of-turn models that the persona hears the agent with: one ONNX session of
each for every call in the process. ONNX Runtime lets many threads run one session at once; each
call keeps its own audio and model state. Pipecat's analyzers build a session each
(pipecat-ai/pipecat#4818 would share them)."""

from onnxruntime import InferenceSession
from pipecat.audio.turn.smart_turn.base_smart_turn import BaseSmartTurn
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroOnnxModel, SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADAnalyzer, VADParams, VADState


class TurnModels:
    """Loads the sessions that Pipecat's own analyzers build, so they keep Pipecat's options."""

    def __init__(self) -> None:
        self._vad = SileroVADAnalyzer()._model.session
        self._end_of_turn = LocalSmartTurnAnalyzerV3()._session

    def vad(self, *, sample_rate: int, params: VADParams) -> SileroVADAnalyzer:
        return SharedSileroVAD(self._vad, sample_rate=sample_rate, params=params)

    def end_of_turn(self) -> LocalSmartTurnAnalyzerV3:
        return SharedSmartTurn(self._end_of_turn)


class SharedSileroModel(SileroOnnxModel):
    def __init__(self, session: InferenceSession) -> None:
        self.session = session
        self.sample_rates = [8000, 16000]
        self.reset_states()


class SharedSileroVAD(SileroVADAnalyzer):
    """Audio goes to the analyzer's thread only when it completes a model window. Pipecat sends
    each frame there, and 3 of every 8 frames of 20 ms only fill the buffer."""

    def __init__(self, session: InferenceSession, *, sample_rate: int, params: VADParams) -> None:
        VADAnalyzer.__init__(self, sample_rate=sample_rate, params=params)
        self._model = SharedSileroModel(session)
        self._windows_since_reset = 0
        self._low_confidence_windows = 0

    async def analyze_audio(self, buffer: bytes) -> VADState:
        if len(self._vad_buffer) + len(buffer) < self._vad_frames_num_bytes:
            self._vad_buffer += buffer
            return self._vad_state
        return await super().analyze_audio(buffer)


class SharedSmartTurn(LocalSmartTurnAnalyzerV3):
    def __init__(self, session: InferenceSession) -> None:
        BaseSmartTurn.__init__(self)
        self._log_data = False
        self._session = session
