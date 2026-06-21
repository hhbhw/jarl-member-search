"""FastAPI entry point for jarl-member-search."""
from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.adi_parser import extract_unique_callsigns, filter_records
from app.cache import JarlCache
from app.callsign_filter import normalize, partition
from app.jarl_client import BATCH_SIZE, JarlClient, JarlResult
from app.qrz_client import QrzApiError, QrzClient

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))

app = FastAPI(title="JARL Member Search")


def _rate_limit() -> float:
    try:
        return float(os.getenv("JARL_RATE_LIMIT_SECONDS", "1.0"))
    except ValueError:
        return 1.0


def _cache_ttl_days() -> int:
    try:
        return int(os.getenv("CACHE_TTL_DAYS", "30"))
    except ValueError:
        return 30


def _get_cache() -> JarlCache:
    return JarlCache(ROOT / "data" / "jarl_cache.sqlite", ttl_seconds=_cache_ttl_days() * 86400)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request, "results": None})


async def _gather_callsigns(
    callsigns: str,
    adi_file: Optional[UploadFile],
    qrz_key: str,
    qrz_start: str,
    qrz_end: str,
) -> tuple[list[str], Optional[str]]:
    """Collect callsigns from text + ADI + QRZ. Returns (callsigns, error_message)."""
    raw_lines = [line.strip() for line in (callsigns or "").replace(",", "\n").splitlines()]
    cs_list = [c for c in raw_lines if c]
    if adi_file is not None and adi_file.filename:
        data = await adi_file.read()
        if data:
            cs_list.extend(extract_unique_callsigns(data))
    qrz_key = (qrz_key or "").strip() or os.getenv("QRZ_API_KEY", "")
    if qrz_key and not qrz_key.lower().startswith("your_"):
        try:
            client = QrzClient(qrz_key)
            cs_list.extend(
                await client.fetch_callsigns(start_date=qrz_start or None, end_date=qrz_end or None)
            )
        except QrzApiError as exc:
            return cs_list, f"QRZ error: {exc}"
        except Exception as exc:  # noqa: BLE001
            return cs_list, f"QRZ network error: {exc}"
    return cs_list, None


async def _run_search(
    callsigns: str,
    adi_file: Optional[UploadFile],
    qrz_key: str = "",
    qrz_start: str = "",
    qrz_end: str = "",
) -> dict:
    cs_list, qrz_error = await _gather_callsigns(callsigns, adi_file, qrz_key, qrz_start, qrz_end)
    queryable, skipped = partition(cs_list)

    cache = _get_cache()
    want = [c.normalized for c in queryable]
    cached = cache.get_many_fresh(want)
    to_query = [cs for cs in want if cs not in cached]

    fresh_results: list[JarlResult] = []
    if to_query:
        async with JarlClient(rate_limit_seconds=_rate_limit()) as client:
            fresh_results = await client.query(to_query)
        cache.put_many(fresh_results)

    fresh_map = {r.callsign: r for r in fresh_results}
    results = []
    for cs in want:
        if cs in cached:
            e = cached[cs]
            results.append(JarlResult(callsign=cs, is_member=e.is_member, qsl_via=e.qsl_via, raw_result=e.raw_result))
        else:
            results.append(fresh_map.get(cs, JarlResult(callsign=cs, is_member="unknown", qsl_via="", raw_result="")))

    return {
        "results": results,
        "skipped": skipped,
        "qrz_error": qrz_error,
        "summary": {
            "total_input": len(cs_list),
            "queried": len(results),
            "from_cache": len(cached),
            "from_jarl": len(to_query),
            "members": sum(1 for r in results if r.is_member == "yes"),
            "non_members": sum(1 for r in results if r.is_member == "no"),
            "unknown": sum(1 for r in results if r.is_member == "unknown"),
            "skipped": len(skipped),
        },
    }


@app.post("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    callsigns: str = Form(""),
    adi_file: Optional[UploadFile] = File(None),
    qrz_key: str = Form(""),
    qrz_start: str = Form(""),
    qrz_end: str = Form(""),
) -> HTMLResponse:
    ctx = await _run_search(callsigns, adi_file, qrz_key, qrz_start, qrz_end)
    return templates.TemplateResponse("index.html", {"request": request, "submitted": callsigns, **ctx})


@app.post("/search.stream")
async def search_stream(
    callsigns: str = Form(""),
    adi_file: Optional[UploadFile] = File(None),
    qrz_key: str = Form(""),
    qrz_start: str = Form(""),
    qrz_end: str = Form(""),
) -> StreamingResponse:
    cs_list, qrz_error = await _gather_callsigns(callsigns, adi_file, qrz_key, qrz_start, qrz_end)

    async def gen():
        def line(obj: dict) -> str:
            return json.dumps(obj, ensure_ascii=False) + "\n"

        if qrz_error:
            yield line({"event": "error", "message": qrz_error})

        queryable, skipped = partition(cs_list)
        cache = _get_cache()
        want = [c.normalized for c in queryable]
        cached = cache.get_many_fresh(want)
        to_query = [cs for cs in want if cs not in cached]

        yield line({
            "event": "start",
            "total_input": len(cs_list),
            "queryable": len(queryable),
            "from_cache": len(cached),
            "from_jarl_planned": len(to_query),
            "batches_planned": (len(to_query) + BATCH_SIZE - 1) // BATCH_SIZE,
            "skipped": [{"original": s.original, "reason": s.reason} for s in skipped],
        })

        # Cached entries — flush immediately in input order so users see something fast.
        for cs in want:
            if cs in cached:
                e = cached[cs]
                yield line({
                    "event": "result",
                    "callsign": cs,
                    "is_member": e.is_member,
                    "qsl_via": e.qsl_via,
                    "raw_result": e.raw_result,
                    "source": "cache",
                })

        # Live JARL queries.
        if to_query:
            async with JarlClient(rate_limit_seconds=_rate_limit()) as client:
                done = 0
                async for batch in client.query_iter(to_query):
                    cache.put_many(batch)
                    for r in batch:
                        yield line({
                            "event": "result",
                            "callsign": r.callsign,
                            "is_member": r.is_member,
                            "qsl_via": r.qsl_via,
                            "raw_result": r.raw_result,
                            "source": "jarl",
                        })
                    done += len(batch)
                    yield line({"event": "progress", "done": done, "total": len(to_query)})

        yield line({"event": "done"})

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/export.adi")
async def export_adi(
    callsigns: str = Form(""),
    adi_file: Optional[UploadFile] = File(None),
    qrz_key: str = Form(""),
    qrz_start: str = Form(""),
    qrz_end: str = Form(""),
) -> Response:
    if adi_file is None or not adi_file.filename:
        raise HTTPException(status_code=400, detail="ADI file required for member-only ADI export")
    adi_bytes = await adi_file.read()
    if not adi_bytes:
        raise HTTPException(status_code=400, detail="ADI file is empty")

    # Run the same search using the uploaded ADI as the source. We pass an
    # already-emptied UploadFile downstream to avoid re-reading; instead, we
    # feed the bytes through callsigns extraction directly.
    extra_calls = extract_unique_callsigns(adi_bytes)
    typed = [line.strip() for line in (callsigns or "").replace(",", "\n").splitlines() if line.strip()]
    all_calls = typed + extra_calls

    # Add QRZ callsigns if a key was supplied (mirrors /search behaviour).
    qrz_key = (qrz_key or "").strip() or os.getenv("QRZ_API_KEY", "")
    if qrz_key and not qrz_key.lower().startswith("your_"):
        try:
            client = QrzClient(qrz_key)
            all_calls.extend(
                await client.fetch_callsigns(start_date=qrz_start or None, end_date=qrz_end or None)
            )
        except Exception:  # noqa: BLE001
            pass  # QRZ failure shouldn't block ADI filtering

    queryable, _ = partition(all_calls)
    cache = _get_cache()
    want = [c.normalized for c in queryable]
    cached = cache.get_many_fresh(want)
    to_query = [cs for cs in want if cs not in cached]

    fresh: list[JarlResult] = []
    if to_query:
        async with JarlClient(rate_limit_seconds=_rate_limit()) as client:
            fresh = await client.query(to_query)
        cache.put_many(fresh)

    members: set[str] = set()
    for cs in want:
        if cs in cached and cached[cs].is_member == "yes":
            members.add(cs)
    for r in fresh:
        if r.is_member == "yes":
            members.add(r.callsign)

    filtered = filter_records(adi_bytes, members, normalize)
    return Response(
        content=filtered,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="jarl_members_only.adi"'},
    )


@app.post("/export.csv")
async def export_csv(
    callsigns: str = Form(""),
    adi_file: Optional[UploadFile] = File(None),
    qrz_key: str = Form(""),
    qrz_start: str = Form(""),
    qrz_end: str = Form(""),
) -> StreamingResponse:
    ctx = await _run_search(callsigns, adi_file, qrz_key, qrz_start, qrz_end)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["callsign", "is_jarl_member", "qsl_via", "raw_result"])
    for r in ctx["results"]:
        writer.writerow([r.callsign, r.is_member, r.qsl_via, r.raw_result])
    for s in ctx["skipped"]:
        writer.writerow([s.original, "skipped", "", s.reason])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="jarl_results.csv"'},
    )


