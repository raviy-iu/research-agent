"""
query_builder.py – Expand user queries with manufacturing context.

Strategy:
1. Detect if the raw query already contains any INDUSTRY_TERMS or TOPIC_TERMS.
2. If no industry term is detected, append a broad manufacturing context phrase
   so sources return industry-relevant results even for generic queries.
3. Build three query variants:
   - `raw`        : the user's original text (verbatim)
   - `expanded`   : raw + manufacturing context suffix (if needed)
   - `keywords`   : individual tokens for field-specific API params

Examples
--------
Input : "FMEA in cement plant"
  → expanded = "FMEA in cement plant"      (already has industry + topic terms)
  → has_industry_term = True, has_topic_term = True

Input : "energy consumption reduction"
  → expanded = "energy consumption reduction manufacturing industrial process"
  → has_industry_term = False, has_topic_term = False
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from config import INDUSTRY_TERMS, TOPIC_TERMS

# Compiled regex patterns for fast term detection
_INDUSTRY_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in INDUSTRY_TERMS) + r")\b",
    re.IGNORECASE,
)
_TOPIC_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in TOPIC_TERMS) + r")\b",
    re.IGNORECASE,
)

# Default context appended when no industry term is present
_DEFAULT_INDUSTRY_CONTEXT = "manufacturing industrial process"

# Common English stop words to skip when building keyword list
_STOP_WORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to",
        "for", "of", "with", "by", "from", "as", "is", "was", "are",
        "be", "been", "being", "have", "has", "had", "do", "does",
        "did", "will", "would", "could", "should", "may", "might",
        "shall", "can", "not", "no", "nor", "so", "yet", "both",
        "either", "neither", "each", "that", "this", "these", "those",
        "it", "its", "their", "they", "we", "our", "you", "your",
        "i", "my", "me", "he", "she", "him", "her", "his",
    }
)


@dataclass
class QueryBundle:
    raw: str
    expanded: str
    keywords: list[str] = field(default_factory=list)
    has_industry_term: bool = False
    has_topic_term: bool = False


def build_query(user_input: str) -> QueryBundle:
    """
    Take the raw CLI query and return a QueryBundle with expanded variants.

    Parameters
    ----------
    user_input : str
        The query string provided by the user at the terminal.

    Returns
    -------
    QueryBundle
        Contains the raw query, an expanded version with manufacturing context
        (if needed), and a keyword list for fine-grained API parameter passing.
    """
    raw = user_input.strip()
    has_industry = bool(_INDUSTRY_RE.search(raw))
    has_topic = bool(_TOPIC_RE.search(raw))

    expanded = raw if has_industry else f"{raw} {_DEFAULT_INDUSTRY_CONTEXT}"

    keywords = _extract_keywords(expanded)

    return QueryBundle(
        raw=raw,
        expanded=expanded,
        keywords=keywords,
        has_industry_term=has_industry,
        has_topic_term=has_topic,
    )


def _extract_keywords(text: str) -> list[str]:
    """Split text into meaningful lowercase tokens, dropping stop words."""
    tokens = re.findall(r"[a-zA-Z0-9]+(?:[_\-][a-zA-Z0-9]+)*", text.lower())
    return [
        t for t in tokens
        if len(t) > 2 and t not in _STOP_WORDS
    ]
