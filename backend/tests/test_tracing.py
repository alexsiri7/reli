"""Tests for Phoenix/OTEL tracing setup."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clear_tracing_env(monkeypatch):
    """Ensure PHOENIX_ENABLED is off by default."""
    monkeypatch.setenv("PHOENIX_ENABLED", "false")


def test_init_tracing_noop_when_disabled():
    """init_tracing should be a no-op when PHOENIX_ENABLED is false."""
    with patch("backend.tracing.settings") as mock_settings:
        mock_settings.phoenix_enabled_bool = False
        mock_settings.PHOENIX_ENABLED = "false"
        from backend.tracing import init_tracing

        # Should not raise
        init_tracing()


def test_init_tracing_configures_provider_when_enabled():
    """init_tracing should set up TracerProvider and OTLP exporter when enabled."""
    with patch("backend.tracing.settings") as mock_settings:
        mock_settings.phoenix_enabled_bool = True
        mock_settings.PHOENIX_ENDPOINT = "http://localhost:6006/v1/traces"
        mock_settings.OTEL_SERVICE_NAME = "reli-test"

        mock_tracer_provider = MagicMock()
        mock_exporter = MagicMock()
        mock_processor = MagicMock()

        with (
            patch("opentelemetry.sdk.trace.TracerProvider", return_value=mock_tracer_provider),
            patch(
                "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter",
                return_value=mock_exporter,
            ) as mock_exp_cls,
            patch(
                "opentelemetry.sdk.trace.export.BatchSpanProcessor",
                return_value=mock_processor,
            ),
            patch("opentelemetry.trace.set_tracer_provider") as mock_set_tp,
        ):
            import backend.tracing

            backend.tracing._tracer_provider = None
            backend.tracing.init_tracing()

            mock_exp_cls.assert_called_once_with(endpoint="http://localhost:6006/v1/traces")
            mock_tracer_provider.add_span_processor.assert_called_once_with(mock_processor)
            mock_set_tp.assert_called_once_with(mock_tracer_provider)


def test_shutdown_tracing_flushes_provider():
    """shutdown_tracing should call shutdown on the tracer provider."""
    import backend.tracing

    mock_provider = MagicMock()
    backend.tracing._tracer_provider = mock_provider

    backend.tracing.shutdown_tracing()

    mock_provider.shutdown.assert_called_once()
    assert backend.tracing._tracer_provider is None


def test_shutdown_tracing_noop_when_not_initialized():
    """shutdown_tracing should be a no-op when no provider exists."""
    import backend.tracing

    backend.tracing._tracer_provider = None
    # Should not raise
    backend.tracing.shutdown_tracing()
