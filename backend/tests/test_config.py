"""Tests for config.yaml loading and per-stage model routing."""

import textwrap
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
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


def test_load_config_errors_when_missing(tmp_path):
    """_load_config raises FileNotFoundError when config.yaml is missing."""
    import pytest

    from backend.agents import _load_config

    missing_path = tmp_path / "nonexistent.yaml"
    with patch("backend.agents._CONFIG_PATH", missing_path), \
         patch("backend.agents._resolve_config_path", return_value=missing_path):
        with pytest.raises(FileNotFoundError, match="config.yaml not found"):
            _load_config()


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

    with patch("backend.agents._CONFIG_PATH", custom), \
         patch("backend.agents._resolve_config_path", return_value=custom):
        cfg = _load_config()

    assert cfg["llm"]["models"]["reasoning"] == "custom/reasoning-model"
    assert cfg["llm"]["models"]["response"] == "custom/response-model"
    assert cfg["llm"]["base_url"] == "https://custom.example.com/v1"


def test_config_staging_yaml_exists():
    """config.staging.yaml must exist at the project root."""
    config_path = Path(__file__).resolve().parent.parent.parent / "config.staging.yaml"
    assert config_path.exists(), f"config.staging.yaml not found at {config_path}"


def test_config_staging_yaml_structure():
    """config.staging.yaml must have the expected structure."""
    config_path = Path(__file__).resolve().parent.parent.parent / "config.staging.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    assert "llm" in cfg
    assert "base_url" in cfg["llm"]
    assert "models" in cfg["llm"]
    models = cfg["llm"]["models"]
    assert "context" in models
    assert "reasoning" in models
    assert "response" in models


def test_resolve_config_path_staging(tmp_path):
    """_resolve_config_path should prefer config.staging.yaml when RELI_ENVIRONMENT=staging."""
    from backend.agents import _resolve_config_path

    staging_config = tmp_path / "config.staging.yaml"
    staging_config.write_text("llm: {}")

    with patch("backend.agents.settings") as mock_settings, \
         patch("backend.agents._PROJECT_ROOT", tmp_path):
        mock_settings.RELI_ENVIRONMENT = "staging"
        result = _resolve_config_path()

    assert result == staging_config


def test_resolve_config_path_falls_back_to_default(tmp_path):
    """_resolve_config_path should fall back to config.yaml when no env-specific file exists."""
    from backend.agents import _resolve_config_path

    with patch("backend.agents.settings") as mock_settings, \
         patch("backend.agents._PROJECT_ROOT", tmp_path), \
         patch("backend.agents._CONFIG_PATH", tmp_path / "config.yaml"):
        mock_settings.RELI_ENVIRONMENT = "staging"
        result = _resolve_config_path()

    assert result == tmp_path / "config.yaml"


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
    """MODEL_PRICING should contain entries for configured models."""
    import backend.agents as agents

    assert len(agents.MODEL_PRICING) > 0
    # The configured models should have pricing (from API fetch or defaults)
    for model in (agents.REQUESTY_MODEL, agents.REQUESTY_REASONING_MODEL, agents.REQUESTY_RESPONSE_MODEL):
        assert model in agents.MODEL_PRICING or agents._strip_provider(model) in {
            agents._strip_provider(k) for k in agents.MODEL_PRICING
        }, f"No pricing found for configured model {model}"


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


# --- Settings production secret validation tests (#437) ---


def test_settings_production_missing_secrets_raises():
    """Settings must raise ValueError when required secrets are missing in production."""
    from backend.config import Settings

    with patch.dict("os.environ", {"RAILWAY_ENVIRONMENT_NAME": "production"}, clear=False):
        with pytest.raises(ValueError, match="Missing required"):
            Settings(SECRET_KEY="", REQUESTY_API_KEY="")


def test_settings_production_with_secrets_passes():
    """Settings should not raise when required secrets are provided in production."""
    from backend.config import Settings

    with patch.dict(
        "os.environ", {"RAILWAY_ENVIRONMENT_NAME": "production"}, clear=False
    ):
        s = Settings(SECRET_KEY="supersecret", REQUESTY_API_KEY="key123")
        assert s.SECRET_KEY == "supersecret"
        assert s.REQUESTY_API_KEY == "key123"


def test_settings_dev_mode_allows_empty_secrets():
    """In dev mode (no RAILWAY_ENVIRONMENT_NAME/PRODUCTION), empty secrets are allowed."""
    from backend.config import Settings

    env_overrides = {
        "RAILWAY_ENVIRONMENT_NAME": "",
        "PRODUCTION": "",
    }
    with patch.dict("os.environ", env_overrides, clear=False):
        # Should not raise, just warn
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            s = Settings(SECRET_KEY="", REQUESTY_API_KEY="")
            assert s.SECRET_KEY == ""
            # Check that a warning was emitted about SECRET_KEY
            secret_warnings = [x for x in w if "SECRET_KEY" in str(x.message)]
            assert len(secret_warnings) >= 1


def test_settings_empty_secret_key_warns():
    """An empty SECRET_KEY should emit a warning even in dev mode."""
    from backend.config import Settings

    env_overrides = {
        "RAILWAY_ENVIRONMENT_NAME": "",
        "PRODUCTION": "",
    }
    with patch.dict("os.environ", env_overrides, clear=False):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Settings(SECRET_KEY="", REQUESTY_API_KEY="somekey")
            secret_warnings = [x for x in w if "authentication is DISABLED" in str(x.message)]
            assert len(secret_warnings) >= 1


# --- RELI_ENVIRONMENT tests ---


def test_settings_reli_environment_defaults_to_development():
    """RELI_ENVIRONMENT should default to 'development'."""
    from backend.config import Settings

    env_overrides = {"RAILWAY_ENVIRONMENT_NAME": "", "PRODUCTION": ""}
    with patch.dict("os.environ", env_overrides, clear=False):
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            s = Settings(SECRET_KEY="", REQUESTY_API_KEY="key")
            assert s.RELI_ENVIRONMENT == "development"
            assert not s.is_staging
            assert not s.is_production


def test_settings_staging_requires_secrets():
    """Staging environment must have required secrets set."""
    from backend.config import Settings

    with pytest.raises(ValueError, match="Missing required staging"):
        Settings(RELI_ENVIRONMENT="staging", SECRET_KEY="", REQUESTY_API_KEY="")


def test_settings_staging_with_secrets_passes():
    """Staging environment should pass validation with required secrets."""
    from backend.config import Settings

    s = Settings(RELI_ENVIRONMENT="staging", SECRET_KEY="secret", REQUESTY_API_KEY="key")
    assert s.is_staging
    assert not s.is_production


def test_settings_sentry_environment_falls_back_to_reli_environment():
    """sentry_environment property should fall back to RELI_ENVIRONMENT when SENTRY_ENVIRONMENT is empty."""
    from backend.config import Settings

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        s = Settings(RELI_ENVIRONMENT="staging", SECRET_KEY="secret", REQUESTY_API_KEY="key", SENTRY_ENVIRONMENT="")
        assert s.sentry_environment == "staging"


def test_settings_sentry_environment_explicit_override():
    """Explicit SENTRY_ENVIRONMENT should take precedence over RELI_ENVIRONMENT."""
    from backend.config import Settings

    s = Settings(RELI_ENVIRONMENT="staging", SECRET_KEY="secret", REQUESTY_API_KEY="key", SENTRY_ENVIRONMENT="custom-env")
    assert s.sentry_environment == "custom-env"
