"""Tests for Phoenix/OTEL tracing setup."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clear_tracing_state(monkeypatch):
    """Ensure PHOENIX_ENABLED is off and tracing state is reset."""
    monkeypatch.setenv("PHOENIX_ENABLED", "false")
    import backend.tracing

    backend.tracing._initialized = False


def test_init_tracing_noop_when_disabled():
    """init_tracing should be a no-op when PHOENIX_ENABLED is false."""
    with patch("backend.tracing.settings") as mock_settings:
        mock_settings.phoenix_enabled_bool = False
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

            backend.tracing._initialized = False
            backend.tracing.init_tracing()

            mock_exp_cls.assert_called_once_with(endpoint="http://localhost:6006/v1/traces")
            mock_tracer_provider.add_span_processor.assert_called_once_with(mock_processor)
            mock_set_tp.assert_called_once_with(mock_tracer_provider)
            assert backend.tracing._initialized is True


def test_shutdown_tracing_flushes_provider():
    """shutdown_tracing should call shutdown on the tracer provider."""
    import backend.tracing

    mock_provider = MagicMock()
    mock_provider.shutdown = MagicMock()
    backend.tracing._initialized = True

    with patch("opentelemetry.trace.get_tracer_provider", return_value=mock_provider):
        backend.tracing.shutdown_tracing()

    mock_provider.shutdown.assert_called_once()
    assert backend.tracing._initialized is False


def test_shutdown_tracing_noop_when_not_initialized():
    """shutdown_tracing should be a no-op when not initialized."""
    import backend.tracing

    backend.tracing._initialized = False
    # Should not raise
    backend.tracing.shutdown_tracing()


def test_get_tracer_returns_tracer():
    """get_tracer should return a tracer instance."""
    from backend.tracing import get_tracer

    tracer = get_tracer()
    # Should return a tracer (no-op when not initialized)
    assert tracer is not None


def test_set_span_error_records_exception():
    """set_span_error should set ERROR status and record the exception."""
    from backend.tracing import set_span_error

    mock_span = MagicMock()
    exc = ValueError("test error")

    set_span_error(mock_span, exc)

    mock_span.set_status.assert_called_once()
    mock_span.record_exception.assert_called_once_with(exc)
