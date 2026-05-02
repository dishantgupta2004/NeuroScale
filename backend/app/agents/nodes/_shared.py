"""
Shared helpers for agent nodes.

Kept tiny on purpose — anything bigger goes in services/.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from loguru import logger

# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


@lru_cache(maxsize=16)
def load_prompt(name: str) -> str:
    """
    Load a prompt template by stem name (no .txt). Cached forever — prompts
    don't change at runtime.
    """
    path = PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# JSON parsing (LLMs sometimes wrap output in ```json fences despite instructions)
# ---------------------------------------------------------------------------
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json_response(text: str) -> dict:
    """
    Best-effort JSON extraction from LLM output.

    Handles:
      - Plain JSON
      - JSON wrapped in ```json ... ``` fences
      - JSON with leading/trailing prose (extracts the first {...} block)

    Raises ValueError if no valid JSON can be found.
    """
    cleaned = _FENCE_RE.sub("", text).strip()

    # Try direct parse first.
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Fall back: find the first balanced {...} block.
    start = cleaned.find("{")
    if start == -1:
        raise ValueError(f"No JSON object in response: {text[:200]}")

    depth = 0
    for i, ch in enumerate(cleaned[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = cleaned[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError as e:
                    raise ValueError(
                        f"Found {{...}} block but it's not valid JSON: {e}"
                    ) from e

    raise ValueError(f"Unbalanced JSON in response: {text[:200]}")


# ---------------------------------------------------------------------------
# Channel format rules — kept here so we don't need an LLM call to know
# "twitter posts are <= 280 chars".
# ---------------------------------------------------------------------------
FORMAT_RULES: dict[str, str] = {
    "blog": (
        "- 600-1200 words\n"
        "- Strong hook in the first sentence\n"
        "- Subheadings for sections\n"
        "- Conclude with a clear takeaway"
    ),
    "linkedin_post": (
        "- 150-300 words\n"
        "- Hook on line 1 (no preamble)\n"
        "- Short paragraphs, line breaks between thoughts\n"
        "- End with a question or CTA"
    ),
    "twitter_post": (
        "- Under 280 characters\n"
        "- Punchy, no hedging\n"
        "- 1-2 hashtags max"
    ),
    "email": (
        "- Subject line (max 60 chars), then body\n"
        "- Greeting -> 2-3 short paragraphs -> sign-off\n"
        "- Single clear call-to-action"
    ),
    "research_summary": (
        "- 300-500 words\n"
        "- Lead with the headline finding\n"
        "- Methodology in one paragraph\n"
        "- Implications + next steps"
    ),
}


def format_rules_for(content_type: str) -> str:
    return FORMAT_RULES.get(content_type, "- Use clear, professional prose")


# ---------------------------------------------------------------------------
# Safe append for state (used when we want to log without crashing on missing keys)
# ---------------------------------------------------------------------------
def trace(node_name: str) -> dict:
    """Returns a partial state update that logs a node visit."""
    logger.info(f"[node] {node_name}")
    return {"node_trace": [node_name]}