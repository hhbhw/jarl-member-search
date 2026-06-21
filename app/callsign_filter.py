"""Japanese callsign filtering.

JARL only assigns membership to holders of Japanese callsigns, so we filter
upstream to avoid wasted requests AND to avoid sending malformed strings
(e.g. with ``/P`` suffix) that JARL's search rejects silently.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Two-letter Japanese amateur prefixes per Charter §3.1.
# JA-JS series (excluding JT which is Mongolia) + 7J-7N + 8J/8N.
JAPAN_PREFIXES: frozenset[str] = frozenset(
    [f"J{c}" for c in "ABCDEFGHIJKLMNOPQRS"]
    + ["7J", "7K", "7L", "7M", "7N", "8J", "8N"]
)

# Suffixes after a slash that we strip before querying JARL.
# These are operating-context markers, not different callsigns.
# Examples: /1 (region), /P (portable), /M (mobile), /MM (maritime mobile),
# /AM (aeronautical mobile), /QRP (low power).
_STRIP_SUFFIX = re.compile(r"/(?:\d+|P|M|MM|AM|QRP|A)$", re.IGNORECASE)

_CALLSIGN_BODY = re.compile(r"^[A-Z0-9]+$")


@dataclass(frozen=True)
class CallsignClassification:
    original: str
    normalized: str  # uppercased, suffix-stripped
    is_japanese: bool
    reason: str  # short tag: 'ok' | 'non_jp_prefix' | 'malformed'


def normalize(callsign: str) -> str:
    """Uppercase and strip trailing operating-suffix.

    Examples
    --------
    >>> normalize('ja1rl')
    'JA1RL'
    >>> normalize('JA1RL/P')
    'JA1RL'
    >>> normalize('7K1ABC/MM')
    '7K1ABC'
    >>> normalize(' JA1RL  ')
    'JA1RL'
    """
    cs = callsign.strip().upper()
    # Strip a single trailing /SUFFIX. JARL portable callsigns like /JA1RL
    # are different — keep those (they are queried as-is).
    cs = _STRIP_SUFFIX.sub("", cs)
    return cs


def is_japanese_prefix(callsign: str) -> bool:
    """Whether the (normalized) callsign starts with a Japanese prefix."""
    cs = callsign.strip().upper()
    if len(cs) < 2:
        return False
    # Most prefixes are 2 letters (JA-JS, 7J-7N, 8J/8N).
    return cs[:2] in JAPAN_PREFIXES


def classify(callsign: str) -> CallsignClassification:
    original = callsign.strip()
    normalized = normalize(callsign)
    if not normalized or not _CALLSIGN_BODY.match(normalized):
        return CallsignClassification(original, normalized, False, "malformed")
    if not is_japanese_prefix(normalized):
        return CallsignClassification(original, normalized, False, "non_jp_prefix")
    return CallsignClassification(original, normalized, True, "ok")


def partition(callsigns: list[str]) -> tuple[list[CallsignClassification], list[CallsignClassification]]:
    """Split into (queryable_japanese, skipped) classifications.

    Deduplicates by normalized callsign while preserving order.
    """
    seen: set[str] = set()
    queryable: list[CallsignClassification] = []
    skipped: list[CallsignClassification] = []
    for cs in callsigns:
        cls = classify(cs)
        key = cls.normalized or cls.original.upper()
        if key in seen:
            continue
        seen.add(key)
        if cls.is_japanese:
            queryable.append(cls)
        else:
            skipped.append(cls)
    return queryable, skipped
