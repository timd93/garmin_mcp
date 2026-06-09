from datetime import datetime, timezone, timedelta

from health_export.timeutil import (
    iso_offset, epoch_ms_to_iso, gmt_iso_to_iso, local_iso, offset_minutes_from_pair,
)


def test_iso_offset_attaches_offset_to_naive_local():
    dt = datetime(2026, 6, 7, 3, 14, 0)
    assert iso_offset(dt, 120) == "2026-06-07T03:14:00+02:00"


def test_iso_offset_preserves_aware_datetime():
    dt = datetime(2026, 6, 7, 3, 14, 0, tzinfo=timezone(timedelta(hours=2)))
    assert iso_offset(dt, 0) == "2026-06-07T03:14:00+02:00"


def test_epoch_ms_to_iso_uses_given_offset():
    # 2026-06-07T01:14:00Z == 03:14 at +02:00
    ms = int(datetime(2026, 6, 7, 1, 14, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert epoch_ms_to_iso(ms, 120) == "2026-06-07T03:14:00+02:00"


def test_gmt_iso_to_iso_treats_string_as_utc():
    assert gmt_iso_to_iso("2026-06-07T01:14:00.0", 120) == "2026-06-07T03:14:00+02:00"


def test_gmt_iso_to_iso_returns_none_on_garbage():
    assert gmt_iso_to_iso("not-a-date", 120) is None


def test_local_iso_attaches_offset_to_local_string():
    assert local_iso("2026-06-07T08:01:00.0", 120) == "2026-06-07T08:01:00+02:00"


def test_offset_minutes_from_pair():
    assert offset_minutes_from_pair("2026-06-07T01:14:00.0", "2026-06-07T03:14:00.0") == 120
    assert offset_minutes_from_pair("2026-06-07T12:00:00", "2026-06-07T07:00:00") == -300
    assert offset_minutes_from_pair(None, "2026-06-07T03:14:00") is None
    assert offset_minutes_from_pair("2026-06-07T01:14:00", None) is None
