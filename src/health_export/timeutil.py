"""Timezone-aware ISO-8601 helpers.

Single responsibility: rendering timestamps as ISO-8601 strings with an
*explicit* UTC offset (e.g. ``2026-06-07T03:14:00+02:00``). Health Connect
requires the zone offset, so naive/bare-UTC strings must never leak out.

Garmin payloads typically carry both a GMT and a local timestamp; the true
offset for that instant is ``local - gmt`` (see :func:`offset_minutes_from_pair`),
which is DST-correct without depending on a separate timezone lookup.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional


def _tz(offset_minutes: int) -> timezone:
    return timezone(timedelta(minutes=offset_minutes))


def _parse_naive(s) -> Optional[datetime]:
    """Parse a Garmin timestamp string to a naive datetime, or None.

    Tolerates a trailing ``Z`` and fractional seconds (``.0`` / ``.123``), which
    fromisoformat handles inconsistently across the forms Garmin emits.
    """
    if not s:
        return None
    text = str(s).replace("Z", "").strip().split(".")[0]
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def iso_offset(dt: datetime, offset_minutes: int) -> str:
    """Return ISO-8601 with an explicit offset.

    A *naive* ``dt`` is treated as local wall-clock time and the offset is
    attached without shifting the clock. An *aware* ``dt`` is left as-is (its
    own offset is preserved); use :func:`epoch_ms_to_iso` / :func:`gmt_iso_to_iso`
    when you need to convert a known-UTC instant into ``offset_minutes``.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tz(offset_minutes))
    return dt.isoformat()


def epoch_ms_to_iso(epoch_ms: int, offset_minutes: int) -> str:
    """Convert a UTC epoch-milliseconds value to ISO-8601 at the given offset."""
    dt = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
    return dt.astimezone(_tz(offset_minutes)).isoformat()


def gmt_iso_to_iso(gmt: str, offset_minutes: int) -> Optional[str]:
    """Parse a naive Garmin GMT timestamp (UTC) and render it at the offset.

    Garmin emits GMT strings like ``"2026-06-07T01:14:00.0"`` with no zone
    information; they are UTC. Returns None if the string can't be parsed.
    """
    dt = _parse_naive(gmt)
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(_tz(offset_minutes)).isoformat()


def local_iso(local: str, offset_minutes: int) -> Optional[str]:
    """Render a naive Garmin *local* wall-clock string with an explicit offset."""
    dt = _parse_naive(local)
    if dt is None:
        return None
    return iso_offset(dt, offset_minutes)


def offset_minutes_from_pair(gmt, local) -> Optional[int]:
    """Derive the UTC offset (minutes) as ``local - gmt``, rounded to the minute.

    Returns None if either timestamp is missing/unparseable, so callers can fall
    back to a request-level offset.
    """
    g = _parse_naive(gmt)
    l = _parse_naive(local)
    if g is None or l is None:
        return None
    return int(round((l - g).total_seconds() / 60))
