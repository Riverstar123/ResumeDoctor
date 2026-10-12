"""Controlled equivalences shipped with matcher-v1, never fuzzy/semantic matches."""

import unicodedata

ALIASES = {
    "js": "javascript",
    "javascript": "javascript",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "ts": "typescript",
    "typescript": "typescript",
}
DEGREES = {"associate": 0, "bachelor": 1, "master": 2, "doctorate": 3}
DEGREE_ALIASES = {"专科": "associate", "本科": "bachelor", "硕士": "master", "博士": "doctorate"}


def normalized_label(label: str) -> str:
    text = " ".join(unicodedata.normalize("NFKC", label).strip().casefold().split())
    return ALIASES.get(text, text)


def normalized_degree(value: str) -> str:
    value = normalized_label(value)
    return DEGREE_ALIASES.get(value, value)
