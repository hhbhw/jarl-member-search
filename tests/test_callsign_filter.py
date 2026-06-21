from app.callsign_filter import classify, normalize, partition


def test_normalize_strips_suffixes():
    assert normalize("JA1RL/P") == "JA1RL"
    assert normalize("ja1rl/p") == "JA1RL"
    assert normalize("7K1ABC/MM") == "7K1ABC"
    assert normalize("JE1ABC/1") == "JE1ABC"
    assert normalize("  JA1RL  ") == "JA1RL"
    assert normalize("JA1RL/QRP") == "JA1RL"


def test_normalize_keeps_main_call_unchanged():
    assert normalize("JA1RL") == "JA1RL"
    assert normalize("8N1HQ") == "8N1HQ"


def test_classify_japanese():
    for cs in ["JA1RL", "JE1ABC", "7K1ABC", "8N1HQ", "JA1RL/P"]:
        c = classify(cs)
        assert c.is_japanese, cs
        assert c.reason == "ok"


def test_classify_non_japanese():
    for cs in ["W1AW", "BG7XXX", "VK2ABC", "DL1XYZ"]:
        c = classify(cs)
        assert not c.is_japanese, cs
        assert c.reason == "non_jp_prefix"


def test_classify_malformed():
    for cs in ["", "???", "JA-RL", "12345"]:
        c = classify(cs)
        assert not c.is_japanese, cs


def test_partition_dedups_and_splits():
    qs, sk = partition(["JA1RL", "JA1RL/P", "BG7XXX", "W1AW", "ja1rl"])
    # JA1RL and JA1RL/P normalize to the same thing, and "ja1rl" too.
    assert [c.normalized for c in qs] == ["JA1RL"]
    assert sorted(c.normalized for c in sk) == ["BG7XXX", "W1AW"]
