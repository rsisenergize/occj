"""Thin OpenAI-compatible client, pointed at Groq by default.

Every caller MUST be able to run without this configured -- the LLM only
ever drafts narrative/rationale text or proposes evidence-grounded
hypotheses; it never sets a score, never decides an action, and every
caller has a deterministic fallback for when llm_configured is False or the
call fails. That's what keeps the system demoable before credentials exist
and resilient in production if the provider has an outage.
"""
import json
import logging

from openai import AsyncOpenAI, APIError, APITimeoutError

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class LLMUnavailable(Exception):
    """Raised whenever the caller should fall back to a deterministic path:
    no credentials configured, a network/provider error, or a response that
    didn't parse as the JSON we asked for."""


_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
    return _client


async def chat_json(*, system: str, user: str) -> dict:
    """Call the model asking for a single JSON object response. Raises
    LLMUnavailable (never lets a raw provider exception escape) so callers
    can uniformly catch-and-fallback."""
    if not settings.llm_configured:
        raise LLMUnavailable("LLM not configured (no API key set)")

    client = _get_client()
    try:
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            timeout=settings.llm_timeout_seconds,
            temperature=0.2,
        )
    except (APIError, APITimeoutError) as exc:
        logger.warning("LLM call failed, falling back to deterministic path: %s", exc)
        raise LLMUnavailable(str(exc)) from exc

    content = response.choices[0].message.content if response.choices else None
    if not content:
        raise LLMUnavailable("Empty LLM response")
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning("LLM returned non-JSON content, falling back: %s", content[:500])
        raise LLMUnavailable("LLM response was not valid JSON") from exc
