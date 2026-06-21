from pathlib import Path

from app.adi_parser import extract_records, filter_records, extract_callsigns
from app.callsign_filter import normalize

FIXTURES = Path(__file__).parent / "fixtures"


def test_extract_records_preserves_call_and_count():
    data = FIXTURES.joinpath("sample.adi").read_bytes()
    header, records = extract_records(data)
    assert "<adif_ver:5>3.1.0" in header
    assert "<eoh>" in header.lower()
    calls = [c for _, c in records]
    # sample.adi has 6 QSOs
    assert calls == ["JA1RL", "JE1ABC", "BG7XYZ", "JA1RL", "7K1ABC/MM", "W1AW"]


def test_filter_records_keeps_only_matching():
    data = FIXTURES.joinpath("sample.adi").read_bytes()
    filtered = filter_records(data, {"JA1RL"}, normalize)
    # Re-extract the resulting bytes to count surviving records.
    _, records = extract_records(filtered)
    calls = [c for _, c in records]
    assert calls == ["JA1RL", "JA1RL"], "Both JA1RL QSOs must survive, others must be dropped"


def test_filter_records_uses_normalizer_for_portable():
    data = FIXTURES.joinpath("sample.adi").read_bytes()
    # 7K1ABC/MM normalizes to 7K1ABC — adding 7K1ABC to keep set should keep
    # that record despite the /MM suffix in the raw ADIF.
    filtered = filter_records(data, {"7K1ABC"}, normalize)
    _, records = extract_records(filtered)
    assert [c for _, c in records] == ["7K1ABC/MM"]


def test_filter_records_preserves_full_qso_fields():
    data = FIXTURES.joinpath("sample.adi").read_bytes()
    filtered = filter_records(data, {"JA1RL"}, normalize).decode("utf-8")
    # The original sample has BAND, MODE, QSO_DATE, TIME_ON for each QSO.
    # Our filter must keep those fields verbatim, not just the CALL.
    assert "<qso_date:8>20240101" in filtered
    assert "<band:3>20m" in filtered
    assert "<mode:3>SSB" in filtered


def test_filter_records_empty_keep_set_drops_everything():
    data = FIXTURES.joinpath("sample.adi").read_bytes()
    filtered = filter_records(data, set(), normalize)
    _, records = extract_records(filtered)
    assert records == []
    # Header must still be present.
    assert "<eoh>" in filtered.decode("utf-8").lower()


def test_filter_records_with_no_header():
    data = b"<call:5>JA1RL<eor>\n<call:6>JE1ABC<eor>\n"
    filtered = filter_records(data, {"JA1RL"}, normalize)
    _, records = extract_records(filtered)
    assert [c for _, c in records] == ["JA1RL"]
