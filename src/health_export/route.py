"""Request param parsing/validation for ``GET /api/health-export``.

Framework-agnostic on purpose: the actual HTTP wiring (auth, client lookup,
response writing) lives in the server's ASGI layer, which calls
:func:`parse_and_validate` and :func:`service.build_bundle`. Keeping this pure
makes the contract (defaults, caps, type filtering, 400 conditions) unit-testable
without a web framework.
"""
from dataclasses import dataclass
from datetime import date as date_cls

from .service import ALL_TYPES

# Generous cap: enough for a full year of backfill, bounded so a single request
# can't fan out into an unbounded per-day Garmin call storm.
MAX_RANGE_DAYS = 370


class ParamError(Exception):
    """Raised for malformed/invalid query params -> HTTP 400."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class Params:
    start: str
    end: str
    types: list | None


def parse_and_validate(query: dict, today: str) -> Params:
    """Validate query params. ``end`` defaults to ``today``; ``types`` is a CSV
    subset of ``ALL_TYPES`` (or ``None`` for all). Raises :class:`ParamError`."""
    start = query.get("start")
    if not start:
        raise ParamError("missing 'start' (YYYY-MM-DD)")
    end = query.get("end") or today
    try:
        s = date_cls.fromisoformat(start)
        e = date_cls.fromisoformat(end)
    except ValueError:
        raise ParamError("dates must be YYYY-MM-DD")
    if s > e:
        raise ParamError("'start' must be <= 'end'")
    if (e - s).days > MAX_RANGE_DAYS:
        raise ParamError(f"range exceeds {MAX_RANGE_DAYS} days")

    types = None
    raw_types = query.get("types")
    if raw_types:
        types = [t.strip() for t in raw_types.split(",") if t.strip()]
        bad = [t for t in types if t not in ALL_TYPES]
        if bad:
            raise ParamError(f"unknown types: {','.join(bad)}")
    return Params(start=s.isoformat(), end=e.isoformat(), types=types)
