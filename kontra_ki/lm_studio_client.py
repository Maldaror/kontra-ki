"""Thin client for LM Studio's OpenAI-compatible chat completions endpoint."""

import os
from urllib.parse import urlsplit

import httpx

LM_STUDIO_BASE = os.environ.get("KONTRA_KI_LM_STUDIO_URL", "http://localhost:1234").rstrip("/")
LM_STUDIO_CHAT_URL = f"{LM_STUDIO_BASE}/v1/chat/completions"
LM_STUDIO_MODELS_URL = f"{LM_STUDIO_BASE}/api/v0/models"
CONFIGURED_MODEL = os.environ.get("KONTRA_KI_MODEL")
API_KEY = os.environ.get("KONTRA_KI_LM_STUDIO_API_KEY")
TIMEOUT_SECONDS = 120
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class LMStudioError(Exception):
    """Raised when LM Studio is unreachable or returns an error response."""


def _validate_endpoint() -> None:
    """Rejects remote endpoints without TLS and explicit authentication."""
    parsed = urlsplit(LM_STUDIO_BASE)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise LMStudioError(
            "KONTRA_KI_LM_STUDIO_URL must be an http:// or https:// URL with a host."
        )
    if parsed.hostname.lower() in LOCAL_HOSTS:
        return
    if parsed.scheme != "https":
        raise LMStudioError(
            "Remote LM Studio endpoints must use HTTPS. Set KONTRA_KI_LM_STUDIO_URL "
            "to an https:// URL."
        )
    if not API_KEY:
        raise LMStudioError(
            "Remote LM Studio endpoints require KONTRA_KI_LM_STUDIO_API_KEY."
        )


def _request_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}


async def _resolve_model(client: httpx.AsyncClient) -> str:
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
        response = await client.get(
            LM_STUDIO_MODELS_URL, headers=_request_headers(), timeout=10
        )
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


async def ask(system_prompt: str, user_content: str) -> str:
    """Sends one chat completion request to LM Studio and returns the reply text.

    Raises:
        LMStudioError: If the model can't be resolved, LM Studio cannot be
            reached, times out, or returns a non-2xx response.
    """
    _validate_endpoint()
    async with httpx.AsyncClient() as client:
        payload = {
            "model": await _resolve_model(client),
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
            response = await client.post(
                LM_STUDIO_CHAT_URL,
                headers=_request_headers(),
                json=payload,
                timeout=TIMEOUT_SECONDS,
            )
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

    body = response.json()
    choices = body.get("choices") or []
    if not choices or "content" not in choices[0].get("message", {}):
        raise LMStudioError(
            f"LM Studio returned an unexpected response shape (no message content): {body}"
        )
    return choices[0]["message"]["content"]
