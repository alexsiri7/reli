"""Tests for config.yaml loading and per-stage model routing."""

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml


def test_config_yaml_exists():
    """config.yaml must exist at the project root."""
    config_path = Path(__file__).resolve().parent.parent.parent / "config.yaml"
    assert config_path.exists(), f"config.yaml not found at {config_path}"


def test_config_yaml_structure():
    """config.yaml must have the expected top-level keys and model entries."""
    config_path = Path(__file__).resolve().parent.parent.parent / "config.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    assert "llm" in cfg
    assert "base_url" in cfg["llm"]
    assert "models" in cfg["llm"]
    models = cfg["llm"]["models"]
    assert "context" in models
    assert "reasoning" in models
    assert "response" in models

    assert "ollama" in cfg
    assert "embedding" in cfg


def test_load_config_defaults(tmp_path):
    """_load_config falls back to defaults when config.yaml is missing."""
    from backend.agents import _load_config

    missing_path = tmp_path / "nonexistent.yaml"
    with patch("backend.agents._CONFIG_PATH", missing_path):
        cfg = _load_config()

    assert cfg["llm"]["models"]["reasoning"] == "google/gemini-2.5-flash"
    assert cfg["llm"]["models"]["context"] == "google/gemini-2.5-flash-lite"
    assert cfg["llm"]["models"]["response"] == "google/gemini-2.5-flash-lite"


def test_load_config_custom(tmp_path):
    """_load_config reads values from a custom config file."""
    custom = tmp_path / "config.yaml"
    custom.write_text(
        textwrap.dedent("""\
        llm:
          base_url: https://custom.example.com/v1
          models:
            context: custom/context-model
            reasoning: custom/reasoning-model
            response: custom/response-model
        """)
    )
    from backend.agents import _load_config

    with patch("backend.agents._CONFIG_PATH", custom):
        cfg = _load_config()

    assert cfg["llm"]["models"]["reasoning"] == "custom/reasoning-model"
    assert cfg["llm"]["models"]["response"] == "custom/response-model"
    assert cfg["llm"]["base_url"] == "https://custom.example.com/v1"


def test_per_stage_model_vars():
    """Module-level model variables must be set from config."""
    import backend.agents as agents

    # These should be non-empty strings
    assert agents.REQUESTY_MODEL
    assert agents.REQUESTY_REASONING_MODEL
    assert agents.REQUESTY_RESPONSE_MODEL
    # Reasoning model should differ from the default context model
    assert agents.REQUESTY_REASONING_MODEL != agents.REQUESTY_MODEL


def test_model_pricing_populated():
    """MODEL_PRICING should contain entries for all configured models."""
    import backend.agents as agents

    assert len(agents.MODEL_PRICING) > 0
    # At minimum, the defaults should be present
    assert "google/gemini-2.5-flash-lite" in agents.MODEL_PRICING
    assert "google/gemini-2.5-flash" in agents.MODEL_PRICING


def test_fetch_requesty_pricing_api_failure():
    """Pricing fetch should fall back to defaults when API is unreachable."""
    from backend.agents import _fetch_requesty_pricing

    with patch("httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__ = lambda self: self
        mock_client_cls.return_value.__exit__ = lambda self, *a: None
        mock_client_cls.return_value.get.side_effect = ConnectionError("unreachable")
        pricing = _fetch_requesty_pricing()

    # Should still have default entries
    assert "google/gemini-2.0-flash-001" in pricing
    assert pricing["google/gemini-2.0-flash-001"] == (0.10, 0.40)


def test_config_pricing_overrides():
    """Config.yaml pricing section should override API/default prices."""
    from backend.agents import _fetch_requesty_pricing

    override_config = {
        "llm": {"base_url": "https://router.requesty.ai/v1", "models": {}},
        "pricing": {
            "google/gemini-2.0-flash-001": {"input": 0.20, "output": 0.80},
        },
    }

    mock_client = MagicMock()
    mock_client.__enter__ = lambda self: self
    mock_client.__exit__ = lambda self, *a: None
    mock_client.get.side_effect = ConnectionError("unreachable")

    with (
        patch("backend.agents._config", override_config),
        patch("httpx.Client", return_value=mock_client),
    ):
        pricing = _fetch_requesty_pricing()

    assert pricing["google/gemini-2.0-flash-001"] == (0.20, 0.80)


def test_estimate_cost_exact_match():
    """estimate_cost should work with exact model name match."""
    from backend.agents import estimate_cost

    cost = estimate_cost("google/gemini-2.5-flash-lite", 1_000_000, 1_000_000)
    assert cost > 0


def test_estimate_cost_without_provider_prefix():
    """estimate_cost should match model names without provider prefix."""
    from backend.agents import estimate_cost

    # "gemini-2.5-flash-lite" should match "google/gemini-2.5-flash-lite"
    cost = estimate_cost("gemini-2.5-flash-lite", 1_000_000, 1_000_000)
    assert cost > 0


def test_estimate_cost_unknown_model():
    """estimate_cost should return 0 for completely unknown models."""
    from backend.agents import estimate_cost

    cost = estimate_cost("unknown/nonexistent-model-xyz", 1000, 1000)
    assert cost == 0.0
