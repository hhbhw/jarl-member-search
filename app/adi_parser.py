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


def _find_call_in_record(record: str) -> str:
    """Return the CALL field value inside a single ADIF record, or empty string."""
    for m in _TAG.finditer(record):
        if m.group(1).upper() == "CALL":
            length = int(m.group(2))
            start = m.end()
            return record[start : start + length].strip().upper()
    return ""


def extract_records(data: bytes | str) -> tuple[str, list[tuple[str, str]]]:
    """Return (header, records) where records is a list of (record_text, callsign).

    ``record_text`` preserves the original bytes between the previous ``<EOR>``
    (or the end of the header) up to and including the next ``<EOR>``. Charter
    §3.1 #10 requires byte-level preservation so downstream consumers see the
    same fields they wrote.
    """
    text = _decode(data) if isinstance(data, bytes) else data

    # Header is everything up to and including <EOH> (if present).
    head_end = _END_TAG.search(text)
    if head_end and head_end.group(1).upper() == "EOH":
        header = text[: head_end.end()]
        body = text[head_end.end() :]
    else:
        header = ""
        body = text

    records: list[tuple[str, str]] = []
    pos = 0
    eor_re = re.compile(r"<eor>", re.IGNORECASE)
    for m in eor_re.finditer(body):
        chunk = body[pos : m.end()]
        call = _find_call_in_record(chunk)
        records.append((chunk, call))
        pos = m.end()
    return header, records


def filter_records(data: bytes | str, keep_callsigns: set[str], normalizer) -> bytes:
    """Return an ADI byte string containing only records whose normalized CALL
    is in ``keep_callsigns``.

    ``normalizer`` is a callable ``(str) -> str`` (typically
    ``callsign_filter.normalize``) used to apply the same suffix-stripping
    we used during the JARL lookup. This makes ``JA1RL/P`` keep the record
    if ``JA1RL`` is in ``keep_callsigns``.

    Header is always preserved as-is. Record bytes are preserved exactly.
    """
    header, records = extract_records(data)
    out = [header]
    for record_text, call in records:
        if not call:
            continue
        if normalizer(call) in keep_callsigns:
            out.append(record_text)
    # Re-join without inserting separators — record_text already includes <EOR>.
    return "".join(out).encode("utf-8")
