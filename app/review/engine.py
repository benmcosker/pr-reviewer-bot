"""The Claude review engine.

Calls the Claude API with structured output so the response is a validated
``Review`` — no brittle JSON string parsing.
"""

from functools import lru_cache

from anthropic import AsyncAnthropic

from ..config import get_settings
from .prompt import SYSTEM_PROMPT
from .schema import Review


@lru_cache
def _client() -> AsyncAnthropic:
    # Constructed lazily so importing this module doesn't require a key.
    settings = get_settings()
    if settings.anthropic_api_key:
        return AsyncAnthropic(api_key=settings.anthropic_api_key)
    return AsyncAnthropic()  # falls back to ANTHROPIC_API_KEY / ant profile


async def review_file(path: str, diff_text: str) -> Review:
    settings = get_settings()
    resp = await _client().messages.parse(
        model=settings.review_model,
        max_tokens=8000,
        thinking={"type": "adaptive"},          # current models reject budget_tokens
        output_config={"effort": "high"},
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},  # cache the stable prefix
            }
        ],
        messages=[
            {
                "role": "user",
                "content": f"File: `{path}`\n\nUnified diff:\n```diff\n{diff_text}\n```",
            }
        ],
        output_format=Review,
    )
    return resp.parsed_output or Review(summary="", findings=[])
