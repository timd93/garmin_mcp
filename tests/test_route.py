import pytest

from health_export.route import parse_and_validate, ParamError


def test_parse_defaults_end_to_today_and_all_types():
    p = parse_and_validate({"start": "2026-06-01"}, today="2026-06-08")
    assert p.start == "2026-06-01" and p.end == "2026-06-08" and p.types is None


def test_parse_rejects_missing_start():
    with pytest.raises(ParamError):
        parse_and_validate({}, today="2026-06-08")


def test_parse_rejects_bad_date_format():
    with pytest.raises(ParamError):
        parse_and_validate({"start": "06/01/2026"}, today="2026-06-08")


def test_parse_rejects_reversed_range():
    with pytest.raises(ParamError):
        parse_and_validate({"start": "2026-06-08", "end": "2026-06-01"}, today="2026-06-08")


def test_parse_rejects_oversized_range():
    with pytest.raises(ParamError):
        parse_and_validate({"start": "2020-01-01", "end": "2026-06-08"}, today="2026-06-08")


def test_parse_types_csv():
    p = parse_and_validate({"start": "2026-06-01", "end": "2026-06-01",
                            "types": "hrv,spo2"}, today="2026-06-08")
    assert p.types == ["hrv", "spo2"]


def test_parse_rejects_unknown_type():
    with pytest.raises(ParamError):
        parse_and_validate({"start": "2026-06-01", "end": "2026-06-01",
                            "types": "hrv,bogus"}, today="2026-06-08")
