import time
from pathlib import Path

from app.cache import JarlCache
from app.jarl_client import JarlResult


def test_put_get_roundtrip(tmp_path: Path):
    cache = JarlCache(tmp_path / "c.sqlite", ttl_seconds=3600)
    cache.put(JarlResult("JA1RL", "yes", "", "○ Yes"))
    e = cache.get_fresh("JA1RL")
    assert e is not None
    assert e.is_member == "yes"
    assert e.raw_result == "○ Yes"


def test_case_insensitive(tmp_path: Path):
    cache = JarlCache(tmp_path / "c.sqlite", ttl_seconds=3600)
    cache.put(JarlResult("ja1rl", "yes", "", "○ Yes"))
    assert cache.get_fresh("JA1RL") is not None
    assert cache.get_fresh("ja1rl") is not None


def test_unknown_not_cached(tmp_path: Path):
    cache = JarlCache(tmp_path / "c.sqlite", ttl_seconds=3600)
    cache.put(JarlResult("JA9XYZ", "unknown", "", ""))
    assert cache.get_fresh("JA9XYZ") is None, "Charter §7.5 forbids caching unknown"


def test_ttl_expiry(tmp_path: Path):
    cache = JarlCache(tmp_path / "c.sqlite", ttl_seconds=10)
    now = int(time.time())
    cache.put(JarlResult("JA1RL", "yes", "", "○ Yes"), now=now - 100)
    assert cache.get_fresh("JA1RL", now=now) is None


def test_get_many(tmp_path: Path):
    cache = JarlCache(tmp_path / "c.sqlite", ttl_seconds=3600)
    cache.put(JarlResult("JA1RL", "yes", "", "○ Yes"))
    cache.put(JarlResult("JE1ABC", "no", "", "×"))
    got = cache.get_many_fresh(["JA1RL", "JE1ABC", "JF9ZZZ"])
    assert set(got.keys()) == {"JA1RL", "JE1ABC"}
    assert got["JA1RL"].is_member == "yes"


def test_upsert_updates_existing(tmp_path: Path):
    cache = JarlCache(tmp_path / "c.sqlite", ttl_seconds=3600)
    cache.put(JarlResult("JA1RL", "no", "", "×"))
    cache.put(JarlResult("JA1RL", "yes", "", "○ Yes"))
    e = cache.get_fresh("JA1RL")
    assert e is not None and e.is_member == "yes"
