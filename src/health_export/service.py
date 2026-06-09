"""Orchestrates fetch + normalize over a date range into one JSON bundle.

Takes a *client-like* object (anything exposing the seven Garmin getter
methods) so it stays network-free and injectable in tests. Each metric is
isolated: a failure on one type/day is recorded in ``errors[]`` and the rest of
the bundle is still produced.
"""
from datetime import date as date_cls, datetime, timezone, timedelta

from . import normalizers as N

ALL_TYPES = ["hrv", "spo2", "respiration", "resting_hr", "vo2max",
             "blood_pressure", "hydration"]


def _daterange(start: str, end: str):
    cur = date_cls.fromisoformat(start)
    last = date_cls.fromisoformat(end)
    while cur <= last:
        yield cur.isoformat()
        cur += timedelta(days=1)


def build_bundle(client, start: str, end: str, offset_minutes: int, types):
    """Build the export bundle for ``[start, end]`` (inclusive).

    ``types`` is a list of metric names to include, or ``None`` for all.
    Returns a dict with one array per metric plus ``errors`` (never raises for
    per-metric/per-day failures).
    """
    wanted = set(types) if types else set(ALL_TYPES)
    bundle = {t: [] for t in ALL_TYPES}
    bundle["start"] = start
    bundle["end"] = end
    bundle["generated_at"] = datetime.now(
        timezone(timedelta(minutes=offset_minutes))).isoformat()
    bundle["errors"] = []

    def safe(metric, date, fn):
        if metric not in wanted:
            return
        try:
            fn()
        except Exception as ex:  # noqa: BLE001 - per-type isolation by design
            bundle["errors"].append({"type": metric, "date": date, "message": str(ex)})

    # Range-based: blood pressure is a single call across the whole range.
    def bp():
        bundle["blood_pressure"].extend(
            N.normalize_blood_pressure(client.get_blood_pressure(start, end), offset_minutes))
    safe("blood_pressure", None, bp)

    # Per-day metrics.
    for d in _daterange(start, end):
        safe("hrv", d, lambda d=d: bundle["hrv"].extend(
            N.normalize_hrv(client.get_hrv_data(d), offset_minutes)))
        safe("spo2", d, lambda d=d: bundle["spo2"].extend(
            N.normalize_spo2(client.get_spo2_data(d), offset_minutes)))
        safe("respiration", d, lambda d=d: bundle["respiration"].extend(
            N.normalize_respiration(client.get_respiration_data(d), offset_minutes)))
        safe("resting_hr", d, lambda d=d: bundle["resting_hr"].extend(
            N.normalize_resting_hr(client.get_rhr_day(d), d, offset_minutes)))
        safe("vo2max", d, lambda d=d: bundle["vo2max"].extend(
            N.normalize_vo2max(client.get_max_metrics(d), d, offset_minutes)))
        safe("hydration", d, lambda d=d: bundle["hydration"].extend(
            N.normalize_hydration(client.get_hydration_data(d), d, offset_minutes)))

    return bundle
