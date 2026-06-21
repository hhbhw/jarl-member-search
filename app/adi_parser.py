"""Minimal ADI/ADIF parser.

We only need the CALL field. ADIF format is just a sequence of
``<FIELDNAME:LENGTH>VALUE`` markers, optionally with a header section
ending in ``<EOH>``. Records end with ``<EOR>``.

Spec reference: https://adif.org/ — we implement the bare minimum needed
to extract callsigns and tolerate noisy files.
"""
from __future__ import annotations

import re
from io import BytesIO

# A single ADIF tag: <NAME:LENGTH> or <NAME:LENGTH:TYPE>
_TAG = re.compile(r"<([A-Za-z_]+):(\d+)(?::[A-Za-z])?>", re.IGNORECASE)
_END_TAG = re.compile(r"<(EOR|EOH)>", re.IGNORECASE)


def _decode(data: bytes) -> str:
    # ADIF spec says ASCII; in practice files are usually UTF-8 with BOM or
    # plain ASCII. Try UTF-8 first, fall back to latin-1 (which never fails).
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def extract_callsigns(data: bytes | str) -> list[str]:
    """Return list of CALL field values from ADI data (order preserved, may contain duplicates)."""
    text = _decode(data) if isinstance(data, bytes) else data

    # Skip header: everything up to and including <EOH>, if present.
    head_end = _END_TAG.search(text)
    if head_end and head_end.group(1).upper() == "EOH":
        text = text[head_end.end():]

    callsigns: list[str] = []
    pos = 0
    while pos < len(text):
        m = _TAG.search(text, pos)
        if not m:
            break
        name = m.group(1).upper()
        length = int(m.group(2))
        value_start = m.end()
        value = text[value_start : value_start + length]
        if name == "CALL":
            cs = value.strip().upper()
            if cs:
                callsigns.append(cs)
        pos = value_start + length
    return callsigns


def extract_unique_callsigns(data: bytes | str) -> list[str]:
    """Like extract_callsigns but deduplicates while preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for cs in extract_callsigns(data):
        if cs not in seen:
            seen.add(cs)
            out.append(cs)
    return out
