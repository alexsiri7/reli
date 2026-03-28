"""OpenTelemetry tracing for the Reli agent pipeline.

Configures a tracer provider that exports spans to Phoenix (or any
OTLP-compatible collector).  Disabled by default — set PHOENIX_ENABLED=true
to activate.

Usage:
    from .tracing import get_tracer

    tracer = get_tracer()
    with tracer.start_as_current_span("my_operation") as span:
        span.set_attribute("key", "value")
"""

import logging

from opentelemetry import trace
from opentelemetry.trace import StatusCode, Tracer

from .config import settings

logger = logging.getLogger(__name__)

_TRACER_NAME = "reli.pipeline"
_initialized = False


def init_tracing() -> None:
    """Initialize the OTEL tracer provider and OTLP exporter.

    Safe to call multiple times — only the first call configures the provider.
    Does nothing when PHOENIX_ENABLED is false.
    """
    global _initialized
    if _initialized or not settings.phoenix_enabled_bool:
        return

    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": settings.OTEL_SERVICE_NAME})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=settings.PHOENIX_ENDPOINT)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        # Auto-instrument Google ADK agents for LLM call spans
        try:
            from openinference.instrumentation.google_adk import ADKInstrumentation

            ADKInstrumentation().instrument(tracer_provider=provider)
            logger.info("ADK auto-instrumentation enabled")
        except Exception:
            logger.warning("openinference-instrumentation-google-adk not available — ADK spans disabled")

        _initialized = True
        logger.info(
            "OTEL tracing initialized — exporting to %s (service: %s)",
            settings.PHOENIX_ENDPOINT,
            settings.OTEL_SERVICE_NAME,
        )
    except Exception:
        logger.exception("Failed to initialize OTEL tracing")


def shutdown_tracing() -> None:
    """Flush and shut down the tracer provider."""
    global _initialized
    provider = trace.get_tracer_provider()
    if _initialized and hasattr(provider, "shutdown"):
        try:
            provider.shutdown()
            logger.info("Tracer provider shut down")
        except Exception:
            logger.exception("Error shutting down tracer provider")
        _initialized = False


def get_tracer(name: str = _TRACER_NAME) -> Tracer:
    """Return an OTEL tracer.

    When tracing is enabled, returns a real tracer from the configured provider.
    When disabled, returns a no-op tracer (spans are created but discarded).

    Args:
        name: Tracer name for span attribution. Defaults to "reli.pipeline".
    """
    return trace.get_tracer(name)


def set_span_error(span: trace.Span, exc: BaseException) -> None:
    """Record an exception on a span and set ERROR status."""
    span.set_status(StatusCode.ERROR, str(exc))
    span.record_exception(exc)
