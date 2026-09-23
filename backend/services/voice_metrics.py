from __future__ import annotations

from prometheus_client import REGISTRY, Counter, Histogram


class VoiceMetrics:
    """
    Prometheus metrics for NOVA's realtime voice lifecycle.

    Labels intentionally remain low-cardinality. User ids, session ids,
    turn ids, transcripts, request contents, and provider payloads are
    never used as metric labels.
    """

    def __init__(self, *, registry=None):
        active_registry = registry if registry is not None else REGISTRY
        self.registry = active_registry
        self.stt_finalization = Histogram(
            "nova_voice_stt_finalization_seconds",
            "Time spent finalizing one realtime STT turn.",
            registry=active_registry,
        )
        self.llm_first_delta = Histogram(
            "nova_voice_llm_first_delta_seconds",
            "Time from voice execution start to the first streamed LLM response delta.",
            registry=active_registry,
        )
        self.tts_first_audio = Histogram(
            "nova_voice_tts_first_audio_seconds",
            "Time from the first assistant text sent to TTS to the first assistant audio event.",
            registry=active_registry,
        )
        self.turn_response = Histogram(
            "nova_voice_turn_response_seconds",
            "Time from voice turn commit to the authoritative assistant response.",
            registry=active_registry,
        )
        self.turn_total = Histogram(
            "nova_voice_turn_total_seconds",
            "Total realtime voice turn duration from turn start to the authoritative assistant response.",
            registry=active_registry,
        )
        self.provider_events = Counter(
            "nova_voice_provider_events_total",
            "Realtime voice provider lifecycle events.",
            labelnames=("provider", "event"),
            registry=active_registry,
        )
        self.errors = Counter(
            "nova_voice_errors_total",
            "Realtime voice errors by stable lifecycle stage and protocol code.",
            labelnames=("stage", "code"),
            registry=active_registry,
        )

    @staticmethod
    def _duration_seconds(value: float) -> float:
        return max(0.0, float(value))

    def observe_stt_finalization(self, duration_seconds: float) -> None:
        self.stt_finalization.observe(self._duration_seconds(duration_seconds))

    def observe_llm_first_delta(self, duration_seconds: float) -> None:
        self.llm_first_delta.observe(self._duration_seconds(duration_seconds))

    def observe_tts_first_audio(self, duration_seconds: float) -> None:
        self.tts_first_audio.observe(self._duration_seconds(duration_seconds))

    def observe_turn_response(self, duration_seconds: float) -> None:
        self.turn_response.observe(self._duration_seconds(duration_seconds))

    def observe_turn_total(self, duration_seconds: float) -> None:
        self.turn_total.observe(self._duration_seconds(duration_seconds))

    def record_provider_event(self, *, provider: str, event: str) -> None:
        self.provider_events.labels(
            provider=str(provider).strip() or "unknown",
            event=str(event).strip() or "unknown",
        ).inc()

    def record_error(self, *, stage: str, code: str) -> None:
        self.errors.labels(
            stage=str(stage).strip() or "unknown",
            code=str(code).strip() or "unknown",
        ).inc()


voice_metrics = VoiceMetrics()
