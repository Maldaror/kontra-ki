"""Thin client for LM Studio's OpenAI-compatible chat completions endpoint."""

import os

import httpx

LM_STUDIO_BASE = "http://localhost:1234"
LM_STUDIO_CHAT_URL = f"{LM_STUDIO_BASE}/v1/chat/completions"
LM_STUDIO_MODELS_URL = f"{LM_STUDIO_BASE}/api/v0/models"
CONFIGURED_MODEL = os.environ.get("KONTRA_KI_MODEL")
TIMEOUT_SECONDS = 120


class LMStudioError(Exception):
    """Raised when LM Studio is unreachable or returns an error response."""


def _resolve_model() -> str:
    """Returns the model to send requests to.

    Uses KONTRA_KI_MODEL if set. Otherwise queries LM Studio's native API (not
    the OpenAI-compatible one, which does not expose load state) for the single
    chat-capable model currently loaded in memory.

    Raises:
        LMStudioError: If LM Studio cannot be reached, or if auto-detection is
            ambiguous (zero or more than one loaded chat-capable model).
    """
    if CONFIGURED_MODEL:
        return CONFIGURED_MODEL

    try:
        response = httpx.get(LM_STUDIO_MODELS_URL, timeout=10)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise LMStudioError(
            f"Could not reach LM Studio at {LM_STUDIO_MODELS_URL} to auto-detect the "
            "loaded model. Is the local server running (Developer tab -> Start "
            "Server)? You can also set KONTRA_KI_MODEL explicitly."
        ) from exc

    loaded_chat_models = [
        model["id"]
        for model in response.json().get("data", [])
        if model.get("state") == "loaded" and model.get("type") != "embeddings"
    ]

    if len(loaded_chat_models) == 1:
        return loaded_chat_models[0]
    if not loaded_chat_models:
        raise LMStudioError(
            "LM Studio has no chat-capable model loaded. Load one in LM Studio, or "
            "set KONTRA_KI_MODEL explicitly."
        )
    raise LMStudioError(
        "LM Studio has multiple loaded chat-capable models "
        f"({', '.join(loaded_chat_models)}) - set KONTRA_KI_MODEL to disambiguate."
    )


def ask(system_prompt: str, user_content: str) -> str:
    """Sends one chat completion request to LM Studio and returns the reply text.

    Raises:
        LMStudioError: If the model can't be resolved, LM Studio cannot be
            reached, times out, or returns a non-2xx response.
    """
    payload = {
        "model": _resolve_model(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        # Low temperature on purpose: this is an audit/critique task, not creative
        # writing. High temperature encouraged the model to free-associate generic
        # best-practice concerns instead of staying anchored to the actual input.
        "temperature": 0.25,
    }

    try:
        response = httpx.post(LM_STUDIO_CHAT_URL, json=payload, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.ConnectError as exc:
        raise LMStudioError(
            f"Could not reach LM Studio at {LM_STUDIO_CHAT_URL}. Is the local server "
            "running (Developer tab -> Start Server)?"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise LMStudioError(
            f"LM Studio returned HTTP {exc.response.status_code}: {exc.response.text}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise LMStudioError(
            f"LM Studio did not respond within {TIMEOUT_SECONDS}s (timeout)."
        ) from exc

    return response.json()["choices"][0]["message"]["content"]
