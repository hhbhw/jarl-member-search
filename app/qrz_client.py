"""QRZ Logbook API client.

API: https://logbook.qrz.com/api  (POST, x-www-form-urlencoded)

Response is an &-joined ``KEY=VALUE`` form where the ADIF field is
HTML-entity-escaped (e.g. ``&lt;call:5&gt;JA1RL``). We URL-decode and
HTML-unescape before handing off to ``adi_parser``.
"""
from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from typing import Optional
import httpx

from app.adi_parser import extract_unique_callsigns

log = logging.getLogger(__name__)

QRZ_URL = "https://logbook.qrz.com/api"
TIMEOUT = 60.0


@dataclass(frozen=True)
class QrzStatus:
    callsign: str
    count: int
    start_date: str
    end_date: str


class QrzApiError(RuntimeError):
    pass


def _parse_response(body: str) -> dict[str, str]:
    """Parse QRZ's ``&``-joined ``KEY=VALUE`` response.

    The ADIF field's value contains many ``&`` characters (one between every
    HTML-escaped tag), so ``parse_qs`` chops it to pieces. We special-case
    ADIF: take everything after ``ADIF=`` up to end of body.
    """
    fields: dict[str, str] = {}
    adif_idx = body.find("ADIF=")
    head = body if adif_idx < 0 else body[:adif_idx]
    # Drop trailing & before ADIF= if present.
    head = head.rstrip("&")
    if head:
        for part in head.split("&"):
            if "=" not in part:
                continue
            k, _, v = part.partition("=")
            fields[k] = v
    if adif_idx >= 0:
        fields["ADIF"] = body[adif_idx + len("ADIF=") :]
    return fields


class QrzClient:
    def __init__(self, api_key: str, timeout: float = TIMEOUT) -> None:
        if not api_key or api_key.strip().lower().startswith("your_"):
            raise QrzApiError("QRZ_API_KEY not set (still the placeholder)")
        self._key = api_key.strip()
        self._timeout = timeout

    async def status(self) -> QrzStatus:
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(QRZ_URL, data={"KEY": self._key, "ACTION": "STATUS"})
        r.raise_for_status()
        body = _parse_response(r.text)
        if body.get("RESULT") != "OK":
            reason = (body.get("REASON") or "").strip() or body.get("RESULT", "unknown")
            raise QrzApiError(
                f"QRZ STATUS failed: {reason}. "
                "Make sure the key comes from the logbook's Settings (not your account API key), "
                "and that the logbook has at least one QSO and HTTP API enabled."
            )
        return QrzStatus(
            callsign=body.get("CALLSIGN", ""),
            count=int(body.get("COUNT", "0") or 0),
            start_date=body.get("START_DATE", ""),
            end_date=body.get("END_DATE", ""),
        )

    async def fetch_adi(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> str:
        """Return raw ADIF text for QSOs in the given date range.

        Dates are YYYY-MM-DD (HTML date input format, matches QRZ).
        Per QRZ docs, BETWEEN takes ``YYYY-MM-DD+YYYY-MM-DD`` (plus, not comma).
        If both dates omitted, fetches the whole logbook.
        """
        options = []
        if start_date and end_date:
            options.append(f"BETWEEN:{start_date}+{end_date}")
        elif start_date:
            options.append(f"BETWEEN:{start_date}+2099-12-31")
        elif end_date:
            options.append(f"BETWEEN:1970-01-01+{end_date}")
        opt = ",".join(options)

        data = {"KEY": self._key, "ACTION": "FETCH"}
        if opt:
            data["OPTION"] = opt

        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(QRZ_URL, data=data)
        r.raise_for_status()
        body = _parse_response(r.text)
        if body.get("RESULT") != "OK":
            reason = (body.get("REASON") or "").strip()
            count = int(body.get("COUNT", "0") or 0)
            # If QRZ gave a REASON, surface it — could be auth, disabled API,
            # malformed range, or anything else worth telling the user.
            if reason:
                raise QrzApiError(f"QRZ FETCH failed: {reason}")
            # No REASON and zero count + we asked for a date range → likely
            # a legitimately empty window. Treat as empty.
            if count == 0 and opt:
                return ""
            # No REASON and zero count with NO filter → almost always means
            # the logbook is empty or the key is invalid. Tell the user.
            if count == 0:
                raise QrzApiError(
                    "QRZ returned 0 records with no filter. Either the logbook is empty, "
                    "the API key is invalid, or Logbook API access is disabled for that account "
                    "(check the logbook's Settings → API)."
                )
            raise QrzApiError(f"QRZ FETCH failed: {body.get('RESULT')}")
        adif_escaped = body.get("ADIF", "")
        # QRZ HTML-escapes the ADIF angle brackets (&lt;call:5&gt;).
        return html.unescape(adif_escaped)

    async def fetch_callsigns(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> list[str]:
        """Convenience: fetch ADI and extract unique CALL fields."""
        adi = await self.fetch_adi(start_date=start_date, end_date=end_date)
        return extract_unique_callsigns(adi)
