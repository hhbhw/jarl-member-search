"""JARL MemberSearch client.

Posts to the ASP.NET WebForm at
https://www.jarl.com/Page/Search/MemberSearch.aspx?Language=Jp
and parses the ListView result rows.

JARL's form natively supports up to 20 callsigns per query when separated
by half-width spaces. We use that to minimise request count.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Iterable

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

JARL_URL = "https://www.jarl.com/Page/Search/MemberSearch.aspx?Language=Jp"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) jarl-member-search/0.1"
BATCH_SIZE = 20  # JARL native limit
REQUEST_TIMEOUT = 30.0


@dataclass
class JarlResult:
    callsign: str
    is_member: str  # 'yes' | 'no' | 'unknown'
    qsl_via: str  # empty unless raw_result has 'via XXX'
    raw_result: str  # original JARL string, e.g. '○ Yes' / '×' / '○ Yes via JG1XYZ'


def _classify(raw: str) -> tuple[str, str]:
    """Return (is_member, qsl_via) from a raw JARL result string.

    JARL semantics (from the page legend):
      ○ Yes / YES                          → member, QSL forwardable
      ○ No  / NO                           → member, QSL NOT forwardable
      ×                                    → not a member (or hidden)
      ○ Yes via {callsign}                 → member, QSL via that callsign
      ○ YES **/{callsign}/** via {callsign} → member operating overseas
    """
    s = raw.strip()
    if not s:
        return ("unknown", "")

    # Anything with × is the "not a member / hidden" bucket.
    if "×" in s or "✕" in s:
        return ("no", "")

    # The "○" mark (full-width circle) indicates membership. JARL also uses
    # "Yes"/"No" (case-insensitive) in the same string.
    has_circle = "○" in s or "◯" in s
    has_yes_or_no = ("yes" in s.lower()) or ("no" in s.lower())
    if has_circle or has_yes_or_no:
        via = ""
        # Look for "via {callsign}" — the callsign that forwards QSL on this
        # member's behalf.
        lower = s.lower()
        if " via " in lower:
            tail = s.split("via", 1)[1].strip()
            # Strip trailing markup-ish noise; callsigns are A-Z0-9/ only.
            via_chars = []
            for ch in tail:
                if ch.isalnum() or ch in "/-":
                    via_chars.append(ch.upper())
                elif via_chars:
                    break
            via = "".join(via_chars)
        return ("yes", via)

    return ("unknown", "")


def _parse_form_state(html: str) -> dict[str, str]:
    """Extract the ASP.NET hidden fields needed to POST back."""
    soup = BeautifulSoup(html, "html.parser")
    fields = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        tag = soup.find("input", attrs={"name": name})
        if tag and tag.get("value") is not None:
            fields[name] = tag["value"]
    return fields


def _parse_results(html: str) -> list[tuple[str, str]]:
    """Return list of (callsign, raw_result) pairs from a JARL response HTML."""
    soup = BeautifulSoup(html, "html.parser")
    pairs: list[tuple[str, str]] = []
    i = 0
    while True:
        call_tag = soup.find("span", id=f"ListView1_lblCallSign_{i}")
        res_tag = soup.find("span", id=f"ListView1_lblResult_{i}")
        if call_tag is None or res_tag is None:
            break
        pairs.append((call_tag.get_text(strip=True).upper(), res_tag.get_text(strip=True)))
        i += 1
    return pairs


class JarlClient:
    """Async client that batches up to 20 callsigns per JARL request."""

    def __init__(
        self,
        rate_limit_seconds: float = 1.0,
        max_retries: int = 3,
        timeout: float = REQUEST_TIMEOUT,
    ) -> None:
        self.rate_limit_seconds = rate_limit_seconds
        self.max_retries = max_retries
        self._client: httpx.AsyncClient | None = None
        self._state: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._timeout = timeout

    async def __aenter__(self) -> "JarlClient":
        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
        await self._refresh_state()
        return self

    async def __aexit__(self, *_exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _refresh_state(self) -> None:
        assert self._client is not None
        resp = await self._client.get(JARL_URL)
        resp.raise_for_status()
        self._state = _parse_form_state(resp.text)
        if not self._state.get("__VIEWSTATE"):
            raise RuntimeError("JARL page did not return __VIEWSTATE; layout may have changed")

    async def _post_batch(self, callsigns: list[str]) -> list[JarlResult]:
        assert self._client is not None
        if not callsigns:
            return []

        query = " ".join(callsigns)
        form = {
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "__LASTFOCUS": "",
            "__VIEWSTATE": self._state.get("__VIEWSTATE", ""),
            "__VIEWSTATEGENERATOR": self._state.get("__VIEWSTATEGENERATOR", ""),
            "__EVENTVALIDATION": self._state.get("__EVENTVALIDATION", ""),
            "txtCallSign": query,
            "btnSearch": "検　索",  # full-width space, matches form's value
            "hdnMemberType": "Jp",
        }
        resp = await self._client.post(JARL_URL, data=form)
        resp.raise_for_status()
        # Update state for next postback (ASP.NET rotates VIEWSTATE).
        new_state = _parse_form_state(resp.text)
        if new_state:
            self._state = new_state

        pairs = _parse_results(resp.text)
        results_by_call = {c.upper(): r for c, r in pairs}
        out: list[JarlResult] = []
        for cs in callsigns:
            raw = results_by_call.get(cs.upper(), "")
            if not raw:
                out.append(JarlResult(callsign=cs, is_member="unknown", qsl_via="", raw_result=""))
                continue
            status, via = _classify(raw)
            out.append(JarlResult(callsign=cs, is_member=status, qsl_via=via, raw_result=raw))
        return out

    async def query(self, callsigns: Iterable[str]) -> list[JarlResult]:
        """Query JARL for membership status of multiple callsigns.

        Batches into groups of BATCH_SIZE, sleeps `rate_limit_seconds` between
        batches, and retries each batch up to `max_retries` times with
        exponential backoff.
        """
        if self._client is None:
            raise RuntimeError("Use 'async with JarlClient() as c:'")

        cs_list = [c.strip().upper() for c in callsigns if c and c.strip()]
        # Deduplicate while preserving order.
        seen: set[str] = set()
        unique: list[str] = []
        for cs in cs_list:
            if cs not in seen:
                seen.add(cs)
                unique.append(cs)

        all_results: list[JarlResult] = []
        async with self._lock:
            for i in range(0, len(unique), BATCH_SIZE):
                batch = unique[i : i + BATCH_SIZE]
                if i > 0:
                    await asyncio.sleep(self.rate_limit_seconds)
                batch_results = await self._post_batch_with_retry(batch)
                all_results.extend(batch_results)
        return all_results

    async def _post_batch_with_retry(self, batch: list[str]) -> list[JarlResult]:
        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return await self._post_batch(batch)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                log.warning("JARL batch failed (attempt %d/%d): %s", attempt + 1, self.max_retries, exc)
                await asyncio.sleep(delay)
                delay *= 2
                # On retry, refresh state in case viewstate became invalid.
                try:
                    await self._refresh_state()
                except Exception:  # noqa: BLE001, S110
                    pass
        log.error("JARL batch giving up after %d attempts: %s", self.max_retries, last_exc)
        return [JarlResult(callsign=cs, is_member="unknown", qsl_via="", raw_result="") for cs in batch]
