"""Orchestrates fetch + normalize over a date range into one JSON bundle.

Takes a *client-like* object (anything exposing the seven Garmin getter
methods) so it stays network-free and injectable in tests. Each metric is
isolated: a failure on one type/day is recorded in ``errors[]`` and the rest of
the bundle is still produced.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date as date_cls, datetime, timezone, timedelta

from . import normalizers as N

ALL_TYPES = ["hrv", "spo2", "respiration", "resting_hr", "vo2max",
             "blood_pressure", "hydration"]

_FETCH_WORKERS = 8


def _daterange(start: str, end: str):
    cur = date_cls.fromisoformat(start)
    last = date_cls.fromisoformat(end)
    while cur <= last:
        yield cur.isoformat()
        cur += timedelta(days=1)


def _fetch_day(client, d: str, wanted: set, offset_minutes: int):
    """Fetch and normalize all requested per-day metrics for one date.

    Returns (rows_by_type, errors) where rows_by_type maps metric name -> list.
    """
    rows = {t: [] for t in ALL_TYPES}
    errors = []

    def safe(metric, fn):
        if metric not in wanted:
            return
        try:
            fn()
        except Exception as ex:  # noqa: BLE001
            errors.append({"type": metric, "date": d, "message": str(ex)})

    safe("hrv", lambda: rows["hrv"].extend(
        N.normalize_hrv(client.get_hrv_data(d), offset_minutes)))
    safe("spo2", lambda: rows["spo2"].extend(
        N.normalize_spo2(client.get_spo2_data(d), offset_minutes)))
    safe("respiration", lambda: rows["respiration"].extend(
        N.normalize_respiration(client.get_respiration_data(d), offset_minutes)))
    safe("resting_hr", lambda: rows["resting_hr"].extend(
        N.normalize_resting_hr(client.get_rhr_day(d), d, offset_minutes)))
    safe("vo2max", lambda: rows["vo2max"].extend(
        N.normalize_vo2max(client.get_max_metrics(d), d, offset_minutes)))
    safe("hydration", lambda: rows["hydration"].extend(
        N.normalize_hydration(client.get_hydration_data(d), d, offset_minutes)))

    return rows, errors


def build_bundle(client, start: str, end: str, offset_minutes: int, types):
    """Build the export bundle for ``[start, end]`` (inclusive).

    ``types`` is a list of metric names to include, or ``None`` for all.
    Returns a dict with one array per metric plus ``errors`` (never raises for
    per-metric/per-day failures). Per-day fetches are parallelised across a
    thread pool so wide date ranges don't stall on sequential network I/O.
    """
    wanted = set(types) if types else set(ALL_TYPES)
    bundle = {t: [] for t in ALL_TYPES}
    bundle["start"] = start
    bundle["end"] = end
    bundle["generated_at"] = datetime.now(
        timezone(timedelta(minutes=offset_minutes))).isoformat()
    bundle["errors"] = []

    # Range-based: blood pressure is a single call across the whole range.
    if "blood_pressure" in wanted:
        try:
            bundle["blood_pressure"].extend(
                N.normalize_blood_pressure(client.get_blood_pressure(start, end), offset_minutes))
        except Exception as ex:  # noqa: BLE001
            bundle["errors"].append({"type": "blood_pressure", "date": None, "message": str(ex)})

    # Per-day metrics — fetched in parallel.
    dates = list(_daterange(start, end))
    with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
        futures = {pool.submit(_fetch_day, client, d, wanted, offset_minutes): d for d in dates}
        for fut in as_completed(futures):
            rows, errors = fut.result()
            for metric, items in rows.items():
                bundle[metric].extend(items)
            bundle["errors"].extend(errors)

    # Sort each metric array chronologically for deterministic output —
    # as_completed() yields days in nondeterministic order. Rows carry "time"
    # except hydration, whose interval rows carry "start".
    for metric in ALL_TYPES:
        if metric != "blood_pressure":
            bundle[metric].sort(key=lambda r: r.get("time") or r.get("start") or "")

    return bundle
