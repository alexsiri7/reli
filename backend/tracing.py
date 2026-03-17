"""OpenTelemetry tracing setup with Phoenix exporter.

Configures the OTEL tracer provider to export spans to an Arize Phoenix
instance via OTLP/HTTP. Controlled by PHOENIX_ENABLED env var.

Usage:
    from backend.tracing import init_tracing, shutdown_tracing

    # In lifespan:
    init_tracing()
    yield
    shutdown_tracing()
"""

import logging

from .config import settings

logger = logging.getLogger(__name__)

_tracer_provider = None


def init_tracing() -> None:
    """Initialize OTEL tracing with Phoenix OTLP exporter.

    No-op if PHOENIX_ENABLED is not set to true.
    """
    global _tracer_provider

    if not settings.phoenix_enabled_bool:
        logger.info("Phoenix tracing disabled (PHOENIX_ENABLED=%s)", settings.PHOENIX_ENABLED)
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": settings.OTEL_SERVICE_NAME})
        _tracer_provider = TracerProvider(resource=resource)

        exporter = OTLPSpanExporter(endpoint=settings.PHOENIX_ENDPOINT)
        _tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

        trace.set_tracer_provider(_tracer_provider)
        logger.info(
            "Phoenix tracing enabled — exporting to %s (service: %s)",
            settings.PHOENIX_ENDPOINT,
            settings.OTEL_SERVICE_NAME,
        )
    except Exception:
        logger.exception("Failed to initialize Phoenix tracing")


def shutdown_tracing() -> None:
    """Flush and shut down the tracer provider."""
    global _tracer_provider

    if _tracer_provider is not None:
        try:
            _tracer_provider.shutdown()
            logger.info("Phoenix tracer provider shut down")
        except Exception:
            logger.exception("Error shutting down tracer provider")
        _tracer_provider = None
