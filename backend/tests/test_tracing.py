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


def test_get_tracer_with_custom_name():
    """get_tracer with a custom name should return a tracer."""
    from opentelemetry import trace

    from backend.tracing import get_tracer

    tracer = get_tracer("test-module")
    assert isinstance(tracer, trace.Tracer)


def test_set_span_error_records_exception():
    """set_span_error should set ERROR status and record the exception."""
    from backend.tracing import set_span_error

    mock_span = MagicMock()
    exc = ValueError("test error")

    set_span_error(mock_span, exc)

    mock_span.set_status.assert_called_once()
    mock_span.record_exception.assert_called_once_with(exc)


# ---------------------------------------------------------------------------
# _traced_tool decorator tests
# ---------------------------------------------------------------------------


class TestTracedToolDecorator:
    """Tests for the _traced_tool span instrumentation decorator."""

    def test_traced_tool_preserves_function_name(self):
        """Wrapped function should preserve __name__ for ADK schema generation."""
        from backend.reasoning_agent import _traced_tool

        def my_tool(title: str) -> dict:
            """My tool docstring."""
            return {"id": "123", "title": title}

        wrapped = _traced_tool(my_tool)
        assert wrapped.__name__ == "my_tool"
        assert wrapped.__doc__ == "My tool docstring."

    def test_traced_tool_passes_through_result(self):
        """Wrapped tool should return the same result as the original."""
        from backend.reasoning_agent import _traced_tool

        def my_tool(title: str, importance: int = 2) -> dict:
            return {"id": "abc", "title": title, "importance": importance}

        wrapped = _traced_tool(my_tool)
        result = wrapped(title="Test", importance=0)
        assert result == {"id": "abc", "title": "Test", "importance": 0}

    def test_traced_tool_catches_exceptions(self):
        """Wrapped tool should catch exceptions and return error dict."""
        from backend.reasoning_agent import _traced_tool

        def failing_tool(x: str) -> dict:
            raise ValueError("boom")

        wrapped = _traced_tool(failing_tool)
        result = wrapped(x="test")
        assert "error" in result
        assert "boom" in result["error"]

    def test_traced_tool_records_span_attributes(self):
        """Wrapped tool should set span attributes for inputs and outputs."""
        from backend.reasoning_agent import _traced_tool

        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)

        with patch("backend.reasoning_agent._tracer", mock_tracer):

            def create_thing(title: str, importance: int = 2) -> dict:
                return {"id": "new-uuid", "title": title}

            wrapped = _traced_tool(create_thing)
            result = wrapped(title="Buy groceries", importance=0)

        assert result == {"id": "new-uuid", "title": "Buy groceries"}

        # Verify span was started with correct name
        mock_tracer.start_as_current_span.assert_called_once()
        call_args = mock_tracer.start_as_current_span.call_args
        assert call_args[0][0] == "tool.create_thing"

        # Verify input attributes were set
        set_attr_calls = {call[0][0]: call[0][1] for call in mock_span.set_attribute.call_args_list}
        assert set_attr_calls["tool.input.title"] == "Buy groceries"
        assert set_attr_calls["tool.input.importance"] == "0"
        assert "new-uuid" in set_attr_calls["tool.output"]
        assert set_attr_calls["tool.result.id"] == "new-uuid"

    def test_traced_tool_records_error_status_on_error_result(self):
        """Wrapped tool should set ERROR status when result contains 'error' key."""
        from backend.reasoning_agent import _traced_tool

        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)

        with patch("backend.reasoning_agent._tracer", mock_tracer):

            def bad_tool(thing_id: str) -> dict:
                return {"error": "Thing not found"}

            wrapped = _traced_tool(bad_tool)
            result = wrapped(thing_id="missing")

        assert result == {"error": "Thing not found"}

        set_attr_calls = {call[0][0]: call[0][1] for call in mock_span.set_attribute.call_args_list}
        assert set_attr_calls["tool.error"] == "Thing not found"

    def test_tools_from_factory_are_traced(self):
        """Tools returned by _make_reasoning_tools should be wrapped with tracing."""
        with (
            patch("backend.reasoning_agent.upsert_thing"),
            patch("backend.reasoning_agent.vs_delete"),
        ):
            from backend.reasoning_agent import _make_reasoning_tools

            tools, _, _fetched = _make_reasoning_tools("test-user")

        # All tools should still have their original names (via functools.wraps)
        names = [t.__name__ for t in tools]
        assert names == [
            "fetch_context",
            "chat_history",
            "create_thing",
            "update_thing",
            "delete_thing",
            "merge_things",
            "create_relationship",
        ]
