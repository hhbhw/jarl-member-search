from pathlib import Path

from app.adi_parser import extract_callsigns, extract_unique_callsigns

FIXTURES = Path(__file__).parent / "fixtures"


def test_extract_basic():
    data = FIXTURES.joinpath("sample.adi").read_bytes()
    calls = extract_callsigns(data)
    assert calls == ["JA1RL", "JE1ABC", "BG7XYZ", "JA1RL", "7K1ABC/MM", "W1AW"]


def test_extract_unique_preserves_order():
    data = FIXTURES.joinpath("sample.adi").read_bytes()
    assert extract_unique_callsigns(data) == ["JA1RL", "JE1ABC", "BG7XYZ", "7K1ABC/MM", "W1AW"]


def test_handles_no_header():
    data = b"<call:5>JA1RL <eor>\n<call:6>JE1ABC <eor>\n"
    assert extract_callsigns(data) == ["JA1RL", "JE1ABC"]


def test_handles_mixed_case_tags():
    data = b"<EOH>\n<Call:5>JA1RL<EoR>\n<CALL:6>JE1ABC<eor>\n"
    assert extract_callsigns(data) == ["JA1RL", "JE1ABC"]


def test_handles_typed_tag():
    # <CALL:5:S>JA1RL is valid ADIF (S = string type indicator)
    data = b"<eoh>\n<call:5:S>JA1RL<eor>\n"
    assert extract_callsigns(data) == ["JA1RL"]


def test_empty_input():
    assert extract_callsigns(b"") == []
    assert extract_unique_callsigns(b"") == []
