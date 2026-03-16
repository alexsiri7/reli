"""Settings endpoints: model configuration and usage dashboard via Requesty."""

import logging
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..auth import require_user, user_filter
from ..database import db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config.yaml"


# ── Request/Response models ──────────────────────────────────────────────────


class ModelSettings(BaseModel):
    context: str
    reasoning: str
    response: str
    chat_context_window: int = 3


class ModelSettingsUpdate(BaseModel):
    context: str | None = None
    reasoning: str | None = None
    response: str | None = None
    chat_context_window: int | None = None


class RequestyModel(BaseModel):
    id: str
    name: str | None = None


class UsagePeriod(str, Enum):
    today = "today"
    week = "7d"
    month = "30d"
    all = "all"


class DailyUsage(BaseModel):
    date: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    api_calls: int = 0
    cost_usd: float = 0.0


class ModelBreakdown(BaseModel):
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    api_calls: int = 0
    cost_usd: float = 0.0


class UsageDashboard(BaseModel):
    period: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    api_calls: int = 0
    cost_usd: float = 0.0
    per_model: list[ModelBreakdown] = []
    daily: list[DailyUsage] = []


# ── Helpers ──────────────────────────────────────────────────────────────────


def _read_config() -> dict[str, Any]:
    try:
        with open(_CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def _write_config(cfg: dict[str, Any]) -> None:
    with open(_CONFIG_PATH, "w") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False)


def _reload_agent_vars(models: dict[str, str]) -> None:
    """Update the in-memory module-level model variables in agents.py."""
    import backend.agents as agents_mod

    if "context" in models:
        agents_mod.REQUESTY_MODEL = models["context"]
    if "reasoning" in models:
        agents_mod.REQUESTY_REASONING_MODEL = models["reasoning"]
    if "response" in models:
        agents_mod.REQUESTY_RESPONSE_MODEL = models["response"]


def get_chat_context_window() -> int:
    """Return the configured chat context window size."""
    cfg = _read_config()
    val: int = cfg.get("chat", {}).get("context_window", 3)
    return val


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/models", response_model=list[RequestyModel], summary="List available LLM models")
def list_models(_user_id: str = Depends(require_user)) -> list[RequestyModel]:
    """Proxy the Requesty /v1/models endpoint and return available model IDs."""
    cfg = _read_config()
    base_url = cfg.get("llm", {}).get("base_url", "https://router.requesty.ai/v1")

    try:
        resp = httpx.get(f"{base_url}/models", timeout=10.0)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return [RequestyModel(id=m["id"], name=m.get("name")) for m in data if m.get("id")]
    except Exception as exc:
        logger.warning("Failed to fetch models from Requesty: %s", exc)
        raise HTTPException(status_code=502, detail="Could not fetch models from Requesty API") from exc


@router.get("", response_model=ModelSettings, summary="Get current model settings")
def get_settings(_user_id: str = Depends(require_user)) -> ModelSettings:
    """Return current model configuration for the context, reasoning, and response agents."""
    cfg = _read_config()
    models = cfg.get("llm", {}).get("models", {})
    return ModelSettings(
        context=models.get("context", "google/gemini-2.5-flash-lite"),
        reasoning=models.get("reasoning", "google/gemini-3-flash-preview"),
        response=models.get("response", "google/gemini-2.5-flash-lite"),
        chat_context_window=cfg.get("chat", {}).get("context_window", 3),
    )


@router.put("", response_model=ModelSettings, summary="Update model settings")
def update_settings(
    body: ModelSettingsUpdate,
    _user_id: str = Depends(require_user),
) -> ModelSettings:
    """Update model configuration in config.yaml and reload in-memory vars. Only provided fields are changed."""
    cfg = _read_config()

    if "llm" not in cfg:
        cfg["llm"] = {}
    if "models" not in cfg["llm"]:
        cfg["llm"]["models"] = {}

    updates: dict[str, str] = {}
    if body.context is not None:
        cfg["llm"]["models"]["context"] = body.context
        updates["context"] = body.context
    if body.reasoning is not None:
        cfg["llm"]["models"]["reasoning"] = body.reasoning
        updates["reasoning"] = body.reasoning
    if body.response is not None:
        cfg["llm"]["models"]["response"] = body.response
        updates["response"] = body.response

    if body.chat_context_window is not None:
        if "chat" not in cfg:
            cfg["chat"] = {}
        cfg["chat"]["context_window"] = max(1, min(body.chat_context_window, 50))

    _write_config(cfg)
    _reload_agent_vars(updates)

    models = cfg["llm"]["models"]
    return ModelSettings(
        context=models.get("context", "google/gemini-2.5-flash-lite"),
        reasoning=models.get("reasoning", "google/gemini-3-flash-preview"),
        response=models.get("response", "google/gemini-2.5-flash-lite"),
        chat_context_window=cfg.get("chat", {}).get("context_window", 3),
    )


@router.get("/usage", response_model=UsageDashboard, summary="Get usage dashboard data")
def get_usage(
    period: UsagePeriod = Query(UsagePeriod.month),
    user_id: str = Depends(require_user),
) -> UsageDashboard:
    """Return token usage, cost, and model breakdown for the given period."""
    now = date.today()
    if period == UsagePeriod.today:
        start = datetime.combine(now, datetime.min.time()).isoformat()
    elif period == UsagePeriod.week:
        start = datetime.combine(now - timedelta(days=6), datetime.min.time()).isoformat()
    elif period == UsagePeriod.month:
        start = datetime.combine(now - timedelta(days=29), datetime.min.time()).isoformat()
    else:
        start = None

    uf_sql, uf_params = user_filter(user_id)
    time_filter = " AND timestamp >= ?" if start else ""
    time_params: list[str] = [start] if start else []

    with db() as conn:
        base_where = f"WHERE 1=1{time_filter}{uf_sql}"
        params = [*time_params, *uf_params]

        totals = conn.execute(
            "SELECT COALESCE(SUM(prompt_tokens), 0) as pt, "
            "COALESCE(SUM(completion_tokens), 0) as ct, "
            "COUNT(*) as calls, COALESCE(SUM(cost_usd), 0) as cost "
            f"FROM usage_log {base_where}",
            params,
        ).fetchone()

        model_rows = conn.execute(
            "SELECT model, COALESCE(SUM(prompt_tokens), 0) as pt, "
            "COALESCE(SUM(completion_tokens), 0) as ct, "
            "COUNT(*) as calls, COALESCE(SUM(cost_usd), 0) as cost "
            f"FROM usage_log {base_where} "
            "GROUP BY model ORDER BY cost DESC",
            params,
        ).fetchall()

        daily_rows = conn.execute(
            "SELECT DATE(timestamp) as day, "
            "COALESCE(SUM(prompt_tokens), 0) as pt, "
            "COALESCE(SUM(completion_tokens), 0) as ct, "
            "COUNT(*) as calls, COALESCE(SUM(cost_usd), 0) as cost "
            f"FROM usage_log {base_where} "
            "GROUP BY DATE(timestamp) ORDER BY day",
            params,
        ).fetchall()

    per_model = [
        ModelBreakdown(
            model=r["model"],
            prompt_tokens=r["pt"],
            completion_tokens=r["ct"],
            total_tokens=r["pt"] + r["ct"],
            api_calls=r["calls"],
            cost_usd=round(r["cost"], 6),
        )
        for r in model_rows
    ]

    daily = [
        DailyUsage(
            date=r["day"],
            prompt_tokens=r["pt"],
            completion_tokens=r["ct"],
            total_tokens=r["pt"] + r["ct"],
            api_calls=r["calls"],
            cost_usd=round(r["cost"], 6),
        )
        for r in daily_rows
    ]

    return UsageDashboard(
        period=period.value,
        prompt_tokens=totals["pt"],
        completion_tokens=totals["ct"],
        total_tokens=totals["pt"] + totals["ct"],
        api_calls=totals["calls"],
        cost_usd=round(totals["cost"], 6),
        per_model=per_model,
        daily=daily,
    )
