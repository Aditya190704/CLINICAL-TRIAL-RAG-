"""Deterministic handling for common instruction-like text in untrusted data."""

from __future__ import annotations

import re

_INSTRUCTION_MARKER = re.compile(
    r"\b(?:ignore|disregard|override|forget|bypass)\b.{0,120}\b"
    r"(?:previous|prior|system|developer|all|safety)?\s*(?:instructions?|prompts?|rules?|polic(?:y|ies))\b"
    r"|\b(?:call|invoke|use)\s+(?:another\s+)?(?:tool|function|shell|filesystem|network|sql)\b"
    r"|\bmark\b.{0,80}\b(?:eligible|excluded|enrolled)\b"
    r"|\b(?:reveal|print|repeat|return)\b.{0,80}\b(?:system prompt|secrets?|credentials?|api key)\b",
    re.I,
)


def contains_instruction_like_text(value: str) -> bool:
    return bool(_INSTRUCTION_MARKER.search(value or ""))


def remove_instruction_like_clauses(value: str) -> str:
    """Drop any sentence or line containing a recognized instruction marker."""
    parts = re.split(r"(?<=[.!?;\n])\s*", value or "")
    return " ".join(
        part.strip()
        for part in parts
        if part.strip() and not contains_instruction_like_text(part)
    ).strip()
