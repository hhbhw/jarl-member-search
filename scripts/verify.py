"""Charter §3.2 verification driver.

Runs three checks and prints PASS/FAIL for each:
  1. Positive: known JARL members are reported as 'yes'
  2. Negative: non-Japanese and malformed callsigns are filtered out
  3. End-to-end: parse the test ADI fixture, classify, query JARL, export CSV
  4. ADI filter: filter the test ADI to members only (Charter §3.1 #10)

Usage:  python scripts/verify.py
Exit code is non-zero if any check fails — suitable for CI or pre-release gate.
"""
from __future__ import annotations

import asyncio
import csv
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.adi_parser import extract_records, extract_unique_callsigns, filter_records  # noqa: E402
from app.callsign_filter import normalize, partition  # noqa: E402
from app.jarl_client import JarlClient  # noqa: E402


KNOWN_MEMBERS = ["JA1RL"]  # JARL HQ station — must be member
KNOWN_NON_JAPANESE = ["W1AW", "BG7XXX", "VK2ABC", "DL1XYZ"]
MALFORMED = ["", "???", "12345"]


async def check_positive() -> bool:
    print(f"[1/3] Positive: querying {KNOWN_MEMBERS!r} expecting 'yes'...")
    async with JarlClient(rate_limit_seconds=0.5) as client:
        results = await client.query(KNOWN_MEMBERS)
    ok = True
    for r in results:
        status = "PASS" if r.is_member == "yes" else "FAIL"
        print(f"    {status}  {r.callsign} -> {r.is_member} (raw={r.raw_result!r})")
        if r.is_member != "yes":
            ok = False
    return ok


def check_negative() -> bool:
    print(f"[2/3] Negative: classifying {KNOWN_NON_JAPANESE + MALFORMED!r} expecting all to be skipped...")
    queryable, skipped = partition(KNOWN_NON_JAPANESE + MALFORMED)
    ok = True
    if queryable:
        for q in queryable:
            print(f"    FAIL  {q.original} would have been queried (normalized={q.normalized})")
            ok = False
    skipped_originals = {s.original for s in skipped}
    expected_filtered = {c for c in KNOWN_NON_JAPANESE + MALFORMED if c}  # empty input is dropped earlier
    missing = expected_filtered - skipped_originals
    for m in missing:
        print(f"    FAIL  {m!r} was not skipped")
        ok = False
    if ok:
        print(f"    PASS  all {len(skipped)} non-Japanese/malformed callsigns correctly skipped")
    return ok


async def check_e2e() -> bool:
    fixture = ROOT / "tests" / "fixtures" / "sample.adi"
    print(f"[3/3] End-to-end: ADI ({fixture.name}) -> filter -> JARL -> CSV...")
    if not fixture.exists():
        print(f"    FAIL  fixture not found: {fixture}")
        return False

    callsigns = extract_unique_callsigns(fixture.read_bytes())
    queryable, skipped = partition(callsigns)
    async with JarlClient(rate_limit_seconds=0.5) as client:
        results = await client.query([q.normalized for q in queryable])

    # Build a CSV in memory and check shape.
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["callsign", "is_jarl_member", "qsl_via", "raw_result"])
    for r in results:
        writer.writerow([r.callsign, r.is_member, r.qsl_via, r.raw_result])

    ok = True
    if not results:
        print("    FAIL  no JARL results produced")
        ok = False
    unknowns = [r for r in results if r.is_member == "unknown"]
    if unknowns:
        print(f"    WARN  {len(unknowns)} unknown results (transient JARL issues?)")
        for u in unknowns:
            print(f"           - {u.callsign}")
    # JA1RL must appear and be yes (sanity from fixture).
    ja1rl = next((r for r in results if r.callsign == "JA1RL"), None)
    if ja1rl is None or ja1rl.is_member != "yes":
        print(f"    FAIL  JA1RL not present or not member: {ja1rl}")
        ok = False
    print(f"    {'PASS' if ok else 'FAIL'}  input={len(callsigns)} queryable={len(queryable)} "
          f"skipped={len(skipped)} members={sum(1 for r in results if r.is_member=='yes')} "
          f"non={sum(1 for r in results if r.is_member=='no')}")
    return ok


async def check_adi_filter() -> bool:
    fixture = ROOT / "tests" / "fixtures" / "sample.adi"
    print(f"[4/4] ADI filter: filtering {fixture.name} by JARL members...")
    data = fixture.read_bytes()
    cs = extract_unique_callsigns(data)
    queryable, _ = partition(cs)
    async with JarlClient(rate_limit_seconds=0.5) as client:
        results = await client.query([q.normalized for q in queryable])
    members = {r.callsign for r in results if r.is_member == "yes"}
    filtered = filter_records(data, members, normalize)
    _, kept = extract_records(filtered)

    kept_calls = [c for _, c in kept]
    expected = "JA1RL"
    ok = True
    if expected not in kept_calls:
        print(f"    FAIL  expected {expected} in filtered ADI, got {kept_calls}")
        ok = False
    bad_calls = [c for c in kept_calls if normalize(c) not in members]
    if bad_calls:
        print(f"    FAIL  non-member records leaked through: {bad_calls}")
        ok = False
    # Check field preservation — pick any kept record, must still have QSO_DATE.
    if kept and "<qso_date" not in kept[0][0].lower():
        print(f"    FAIL  QSO_DATE field missing from kept record: {kept[0][0]!r}")
        ok = False
    if ok:
        print(f"    PASS  kept {len(kept_calls)} records {kept_calls}, all members, QSO fields preserved")
    return ok


async def main() -> int:
    results = [await check_positive(), check_negative(), await check_e2e(), await check_adi_filter()]
    print()
    if all(results):
        print("ALL CHECKS PASS")
        return 0
    print("ONE OR MORE CHECKS FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
