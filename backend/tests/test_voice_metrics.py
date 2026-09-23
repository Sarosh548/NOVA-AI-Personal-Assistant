from __future__ import annotations

from prometheus_client import CollectorRegistry, generate_latest

from services.voice_metrics import VoiceMetrics


def metrics_text(metrics: VoiceMetrics) -> str:
    return generate_latest(metrics.registry).decode("utf-8")


def test_voice_metrics_record_latencies_provider_events_and_errors():
    registry = CollectorRegistry()
    metrics = VoiceMetrics(registry=registry)
    metrics.observe_stt_finalization(0.125)
    metrics.observe_llm_first_delta(0.25)
    metrics.observe_tts_first_audio(0.05)
    metrics.observe_turn_response(0.4)
    metrics.observe_turn_total(1.2)
    metrics.record_provider_event(provider="deepgram", event="stream_started")
    metrics.record_provider_event(provider="elevenlabs", event="stream_started")
    metrics.record_error(stage="tts", code="assistant_audio_failed")

    body = metrics_text(metrics)

    assert "nova_voice_stt_finalization_seconds_count 1.0" in body
    assert "nova_voice_llm_first_delta_seconds_count 1.0" in body
    assert "nova_voice_tts_first_audio_seconds_count 1.0" in body
    assert "nova_voice_turn_response_seconds_count 1.0" in body
    assert "nova_voice_turn_total_seconds_count 1.0" in body
    assert 'nova_voice_provider_events_total{provider="deepgram",event="stream_started"} 1.0' in body
    assert 'nova_voice_provider_events_total{provider="elevenlabs",event="stream_started"} 1.0' in body
    assert 'nova_voice_errors_total{stage="tts",code="assistant_audio_failed"} 1.0' in body


def test_voice_metrics_do_not_expose_identity_in_labels():
    registry = CollectorRegistry()
    metrics = VoiceMetrics(registry=registry)
    metrics.record_error(stage="stt", code="stt_error")
    body = metrics_text(metrics)
    assert "user-001" not in body
    assert "voice-test-user" not in body
    assert "turn-1" not in body
    assert "session-1" not in body


def test_voice_metrics_clamp_negative_duration():
    registry = CollectorRegistry()
    metrics = VoiceMetrics(registry=registry)
    metrics.observe_turn_response(-1.0)
    body = metrics_text(metrics)
    assert "nova_voice_turn_response_seconds_count 1.0" in body
