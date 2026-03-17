"""OpenTelemetry tracing for the Reli agent pipeline.

Configures a tracer provider that exports spans to Phoenix (or any
OTLP-compatible collector).  Disabled by default — set OTEL_ENABLED=true
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
    Does nothing when OTEL_ENABLED is false.
    """
    global _initialized
    if _initialized or not settings.otel_enabled_bool:
        return

    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": settings.OTEL_SERVICE_NAME})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_ENDPOINT)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _initialized = True
        logger.info(
            "OTEL tracing initialized — exporting to %s",
            settings.OTEL_EXPORTER_ENDPOINT,
        )
    except Exception:
        logger.exception("Failed to initialize OTEL tracing")


def get_tracer() -> Tracer:
    """Return the pipeline tracer.

    Returns the no-op tracer when tracing is disabled, so callers never
    need to check whether tracing is active.
    """
    return trace.get_tracer(_TRACER_NAME)


def set_span_error(span: trace.Span, exc: BaseException) -> None:
    """Record an exception on a span and set ERROR status."""
    span.set_status(StatusCode.ERROR, str(exc))
    span.record_exception(exc)
