"""Pure normalizer functions: raw Garmin response -> normalized record dicts.

Each function is total and defensive: missing/unexpected keys yield an empty
list rather than raising, so a malformed payload for one day/metric never breaks
the whole export. No network, no global state — fully unit-testable.

Timestamps: where a payload carries both a GMT and a local timestamp, the
offset is derived per-record as ``local - gmt`` (DST-correct). The
``offset_minutes`` argument is the *fallback* used only when a usable pair is
absent (e.g. date-only metrics, or a payload missing one side).

NOTE: Garmin response field names vary by account/firmware/library version.
The mappings below follow the documented ``garminconnect`` shapes; reconcile
against a captured real response per metric before trusting field names.
"""
from datetime import datetime

from .timeutil import (
    iso_offset, epoch_ms_to_iso, gmt_iso_to_iso, local_iso, offset_minutes_from_pair,
)


def _midnight(date: str) -> datetime:
    """Naive local midnight for a YYYY-MM-DD date."""
    return datetime.fromisoformat(f"{date}T00:00:00")


def _reading_time(gmt, local, fallback_offset):
    """Render a single reading's timestamp, preferring a payload-derived offset.

    If both GMT and local are present, the offset is ``local - gmt``; otherwise
    we attach ``fallback_offset`` to whichever timestamp we have. Returns None if
    neither is usable.
    """
    derived = offset_minutes_from_pair(gmt, local)
    if local:
        return local_iso(local, derived if derived is not None else fallback_offset)
    if gmt:
        return gmt_iso_to_iso(gmt, derived if derived is not None else fallback_offset)
    return None


def _payload_offset(raw: dict, fallback_offset: int) -> int:
    """Per-day offset from a payload's top-level GMT/local pair, else fallback."""
    for gmt_key, local_key in (("startTimestampGMT", "startTimestampLocal"),
                               ("startTimeGMT", "startTimeLocal")):
        derived = offset_minutes_from_pair(raw.get(gmt_key), raw.get(local_key))
        if derived is not None:
            return derived
    return fallback_offset


def normalize_hrv(raw: dict, offset_minutes: int) -> list[dict]:
    """HRV: prefer granular ``hrvReadings``; fall back to the nightly average."""
    if not isinstance(raw, dict):
        return []
    out = []
    for r in raw.get("hrvReadings") or []:
        v = r.get("hrvValue")
        if v is None:
            continue
        t = _reading_time(r.get("readingTimeGMT"), r.get("readingTimeLocal"), offset_minutes)
        if t is None:
            continue
        out.append({"time": t, "rmssd_ms": float(v), "granularity": "reading"})
    if out:
        return out

    summary = raw.get("hrvSummary") or {}
    avg = summary.get("lastNightAvg")
    t = _reading_time(summary.get("createTimeStamp"),
                      summary.get("createTimeStampLocal"), offset_minutes)
    if avg is not None and t is not None:
        return [{"time": t, "rmssd_ms": float(avg), "granularity": "daily"}]
    return []


def normalize_spo2(raw: dict, offset_minutes: int) -> list[dict]:
    """SpO2: ``[epoch_ms, percent]`` readings.

    The live payload uses ``spO2SingleValues`` (granular) with
    ``spO2HourlyAverages`` as the coarser fallback (note the capital O); older
    firmwares used ``spo2ValuesArray``. Descriptors confirm entries are
    ``[timestamp, spo2Reading, ...]`` so ``entry[0]/entry[1]`` works for all.
    Skips null and ``-1`` no-reading sentinels.
    """
    if not isinstance(raw, dict):
        return []
    off = _payload_offset(raw, offset_minutes)
    arr = (raw.get("spO2SingleValues")
           or raw.get("spO2HourlyAverages")
           or raw.get("spo2ValuesArray") or [])
    out = []
    for entry in arr:
        if not entry or len(entry) < 2:
            continue
        ms, pct = entry[0], entry[1]
        if pct is None or pct < 0:
            continue
        out.append({"time": epoch_ms_to_iso(int(ms), off), "percent": int(pct)})
    return out


def normalize_respiration(raw: dict, offset_minutes: int) -> list[dict]:
    """Respiration: ``[epoch_ms, breaths/min]``; Garmin uses negatives as 'no data'."""
    if not isinstance(raw, dict):
        return []
    off = _payload_offset(raw, offset_minutes)
    arr = raw.get("respirationValuesArray") or []
    out = []
    for entry in arr:
        if not entry or len(entry) < 2:
            continue
        ms, val = entry[0], entry[1]
        if val is None or val < 0:
            continue
        out.append({"time": epoch_ms_to_iso(int(ms), off),
                    "breaths_per_min": float(val)})
    return out


def _extract_rhr(raw: dict):
    if raw.get("restingHeartRate") is not None:
        return raw["restingHeartRate"]
    metrics = (((raw.get("allMetrics") or {}).get("metricsMap") or {})
               .get("WELLNESS_RESTING_HEART_RATE") or [])
    for m in metrics:
        if m.get("value") is not None:
            return m["value"]
    return None


def normalize_resting_hr(raw: dict, date: str, offset_minutes: int) -> list[dict]:
    """Resting HR: a single daily value, stamped at local midnight."""
    if not raw:
        return []
    bpm = _extract_rhr(raw)
    if bpm is None:
        return []
    return [{"date": date, "time": iso_offset(_midnight(date), offset_minutes),
             "bpm": int(bpm)}]


def _vo2_value(block: dict):
    if not block:
        return None
    return block.get("vo2MaxPreciseValue") or block.get("vo2MaxValue")


def normalize_vo2max(raw, date: str, offset_minutes: int) -> list[dict]:
    """VO2max: a daily value per sport (running via ``generic``, plus ``cycling``).

    ``get_max_metrics`` returns a list-wrapped dict (``[{"generic": {...}, ...}]``),
    and may return a non-dict (None / "no data" message) when empty — unwrap and
    guard defensively before reading keys.
    """
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    if not isinstance(raw, dict) or not raw:
        return []
    t = iso_offset(_midnight(date), offset_minutes)
    out = []
    for key, sport in (("generic", "running"), ("cycling", "cycling")):
        v = _vo2_value(raw.get(key) or {})
        if v is not None:
            out.append({"date": date, "time": t, "value": float(v), "sport": sport})
    return out


def normalize_blood_pressure(raw: dict, offset_minutes: int) -> list[dict]:
    """Blood pressure: range payload with local + GMT measurement timestamps."""
    if not isinstance(raw, dict):
        return []
    out = []
    for summ in raw.get("measurementSummaries") or []:
        for m in summ.get("measurements") or []:
            sys_, dia = m.get("systolic"), m.get("diastolic")
            t = _reading_time(m.get("measurementTimestampGMT"),
                              m.get("measurementTimestampLocal"), offset_minutes)
            if t is None or sys_ is None or dia is None:
                continue
            out.append({
                "time": t,
                "systolic": int(sys_),
                "diastolic": int(dia),
                "pulse": (int(m["pulse"]) if m.get("pulse") is not None else None),
            })
    return out


def normalize_hydration(raw: dict, date: str, offset_minutes: int) -> list[dict]:
    """Hydration: a daily total, expressed as an interval spanning the local day."""
    if not raw:
        return []
    ml = raw.get("valueInML")
    if not ml:  # None or 0
        return []
    start = _midnight(date)
    end = datetime.fromisoformat(f"{date}T23:59:59")
    return [{
        "date": date,
        "start": iso_offset(start, offset_minutes),
        "end": iso_offset(end, offset_minutes),
        "volume_ml": int(ml),
    }]
