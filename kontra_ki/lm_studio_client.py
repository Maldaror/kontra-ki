"""Thin client for LM Studio's OpenAI-compatible chat completions endpoint."""

import os

import httpx

LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
MODEL = os.environ.get("KONTRA_KI_MODEL", "qwen3.6-35b-a3b")
TIMEOUT_SECONDS = 120


class LMStudioError(Exception):
    """Raised when LM Studio is unreachable or returns an error response."""


def ask(system_prompt: str, user_content: str) -> str:
    """Sends one chat completion request to LM Studio and returns the reply text.

    Raises:
        LMStudioError: If LM Studio cannot be reached, times out, or returns a
            non-2xx response.
    """
    payload = {
        "model": MODEL,
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
        response = httpx.post(LM_STUDIO_URL, json=payload, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.ConnectError as exc:
        raise LMStudioError(
            f"Could not reach LM Studio at {LM_STUDIO_URL}. Is the local server "
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
