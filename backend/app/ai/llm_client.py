"""LLM Client: call OpenRouter's chat completions API with retries.

The API key is the OpenRouter key provisioned by InsForge's Model Gateway,
read from OPENROUTER_API_KEY. It is only ever sent in the Authorization
header and never logged.
"""

import time

import httpx
from loguru import logger

from app.core.config import get_settings

# Worth retrying: rate limits and temporary server problems.
RETRY_STATUS_CODES = {408, 429, 500, 502, 503, 504}
MAX_RETRY_WAIT_SECONDS = 10


class LLMError(Exception):
    """The model could not be reached or returned something unusable.

    `hints` are beginner-friendly things to check, shown in the UI.
    """

    def __init__(self, message: str, hints: list[str] | None = None) -> None:
        super().__init__(message)
        self.hints = hints or []


def _friendly_error(status: int | None, last_error: str, model: str) -> LLMError:
    """Explain the final failure in plain words. The raw error is already in the logs."""
    if status == 401:
        return LLMError(
            "OpenRouter rejected the API key.",
            ["Check OPENROUTER_API_KEY in backend/.env", "Create a new key at https://openrouter.ai/keys and restart the backend"],
        )
    if status == 402:
        return LLMError(
            "Your OpenRouter account has no credits left for this model.",
            ["Use a free model (an id ending in `:free`) in OPENROUTER_MODEL", "Or add credits at https://openrouter.ai/credits"],
        )
    if status in (400, 404):
        return LLMError(
            f"The AI model '{model}' is not available or rejected the request.",
            ["Check OPENROUTER_MODEL in backend/.env against https://openrouter.ai/models", "Pick a model that supports JSON output"],
        )
    if status == 429:
        return LLMError(
            "The AI model is busy right now (rate limited).",
            [
                "Wait a minute and investigate again",
                "Free models are shared and often busy. Try another one in OPENROUTER_MODEL, "
                "for example nvidia/nemotron-3.5-super-vl:free or openrouter/free",
                "Free models also have a daily request limit",
            ],
        )
    if status is not None and status >= 500:
        return LLMError("The AI provider had a temporary problem.", ["Investigate again in a minute"])
    if last_error.startswith("timed out"):
        return LLMError(
            "The AI model took too long to answer.",
            ["Investigate again", "Pick a faster model, or raise OPENROUTER_TIMEOUT_SECONDS in backend/.env"],
        )
    return LLMError(
        "Could not reach OpenRouter.",
        ["Check the backend's internet connection (and proxy, if you use one)", "Investigate again"],
    )


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
        return str(body.get("error", {}).get("message") or body)[:300]
    except ValueError:
        return response.text[:300]


def _retry_wait(attempt: int, response: httpx.Response | None) -> float:
    if response is not None and response.headers.get("retry-after", "").isdigit():
        return min(float(response.headers["retry-after"]), MAX_RETRY_WAIT_SECONDS)
    return min(2.0**attempt, MAX_RETRY_WAIT_SECONDS)  # 1s, 2s, 4s...


def chat_completion(messages: list[dict[str, str]], transport: httpx.BaseTransport | None = None) -> str:
    """Send messages to the model and return the text of its reply.

    `transport` is only for tests (to fake OpenRouter responses).
    """
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise LLMError(
            "AI reasoning is not set up: OPENROUTER_API_KEY is empty.",
            [
                "Get a key from the InsForge dashboard (Model Gateway) or a free account at https://openrouter.ai/keys",
                "Put it in backend/.env as OPENROUTER_API_KEY and restart the backend",
            ],
        )

    payload = {
        "model": settings.openrouter_model,
        "messages": messages,
        "temperature": 0,  # same evidence -> same diagnosis, as far as the model allows
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "X-Title": "AI Kubernetes Agent",
    }
    attempts = settings.openrouter_max_retries + 1
    last_error = "unknown error"
    last_status: int | None = None

    with httpx.Client(
        base_url=settings.openrouter_base_url,
        timeout=settings.openrouter_timeout_seconds,
        transport=transport,
    ) as client:
        for attempt in range(attempts):
            response: httpx.Response | None = None
            started = time.monotonic()
            try:
                response = client.post("/chat/completions", json=payload, headers=headers)
            except httpx.TimeoutException:
                last_error = f"timed out after {settings.openrouter_timeout_seconds}s"
            except httpx.TransportError as exc:
                last_error = f"network error: {exc.__class__.__name__}"
            else:
                if response.status_code == 200:
                    return _read_content(response, settings.openrouter_model, started)
                last_status = response.status_code
                last_error = f"HTTP {response.status_code}: {_error_message(response)}"
                if response.status_code not in RETRY_STATUS_CODES:
                    break  # bad key, unknown model, bad request: retrying will not help

            if attempt < attempts - 1:
                wait = _retry_wait(attempt, response)
                logger.warning("OpenRouter call failed ({}), retrying in {:.0f}s", last_error, wait)
                time.sleep(wait)

    logger.error("OpenRouter call failed after {} attempt(s): {}", attempt + 1, last_error)
    raise _friendly_error(last_status, last_error, settings.openrouter_model)


def _read_content(response: httpx.Response, model: str, started: float) -> str:
    try:
        body = response.json()
    except ValueError as exc:
        raise LLMError("The AI provider sent a broken response.", ["Investigate again"]) from exc

    # OpenRouter can report provider errors inside a 200 response.
    if body.get("error"):
        logger.error("OpenRouter error in body: {}", str(body["error"])[:300])
        raise LLMError("The AI provider returned an error.", ["Investigate again", "If it keeps happening, try another OPENROUTER_MODEL"])

    choices = body.get("choices") or []
    content = (choices[0].get("message") or {}).get("content") if choices else None
    if not content:
        raise LLMError("The AI returned an empty answer.", ["Investigate again", "If it keeps happening, try another OPENROUTER_MODEL"])

    usage = body.get("usage") or {}
    logger.info(
        "OpenRouter {} answered in {:.1f}s ({} prompt + {} completion tokens)",
        body.get("model", model),
        time.monotonic() - started,
        usage.get("prompt_tokens", "?"),
        usage.get("completion_tokens", "?"),
    )
    return content
