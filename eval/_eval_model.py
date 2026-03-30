"""Eval model factory — uses Google AI Studio directly to avoid Requesty quota issues.

If GOOGLE_API_KEY is set, evals use the Gemini API directly via LiteLlm's
gemini/ prefix. Otherwise, falls back to Requesty routing.
"""

import os

from google.adk.models.lite_llm import LiteLlm

from backend.agents import (
    REQUESTY_API_KEY,
    REQUESTY_BASE_URL,
    REQUESTY_MODEL,
    REQUESTY_REASONING_MODEL,
    REQUESTY_RESPONSE_MODEL,
)

_STAGE_MODELS = {
    "context": REQUESTY_MODEL,
    "reasoning": REQUESTY_REASONING_MODEL,
    "response": REQUESTY_RESPONSE_MODEL,
}


def make_eval_model(stage: str = "reasoning") -> LiteLlm:
    """Create a LiteLlm model for evals.

    Uses Google AI Studio directly if GOOGLE_API_KEY is set (avoids
    Requesty shared quota limits on preview models). Falls back to
    Requesty routing otherwise.
    """
    google_api_key = os.environ.get("GOOGLE_API_KEY")
    model_name = _STAGE_MODELS.get(stage, REQUESTY_REASONING_MODEL)

    # Strip provider prefix to get the base model name
    base_name = model_name.rsplit("/", 1)[-1] if "/" in model_name else model_name

    if google_api_key:
        # Use Google AI Studio directly: gemini/ prefix for LiteLlm
        return LiteLlm(
            model=f"gemini/{base_name}",
            api_key=google_api_key,
        )
    else:
        # Fall back to Requesty — openai/ prefix tells LiteLLM to use the
        # OpenAI-compatible provider, and api_base routes to Requesty which
        # handles the google/ provider routing in the model name.
        effective = model_name if model_name.startswith("openai/") else f"openai/{model_name}"
        return LiteLlm(
            model=effective,
            api_key=REQUESTY_API_KEY,
            api_base=REQUESTY_BASE_URL,
        )
