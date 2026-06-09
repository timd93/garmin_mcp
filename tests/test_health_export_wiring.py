"""Tests for the server-side wiring of /api/health-export in garmin_mcp.

garmin_mcp.__init__ imports garminconnect/garth/mcp/requests at module top, none
of which are installed in the system Python used to run these tests, so we stub
them in sys.modules before importing. This lets us exercise the real auth guard,
offset resolution, and the disk-cache client proxy.
"""
import sys
import types

import pytest


def _ensure_stub(name, **attrs):
    try:
        __import__(name)
    except Exception:
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
        return mod
    return sys.modules[name]


@pytest.fixture(scope="module")
def gm():
    # requests (+ requests.exceptions.HTTPError)
    if "requests" not in sys.modules:
        try:
            __import__("requests")
        except Exception:
            req = types.ModuleType("requests")
            exc = types.ModuleType("requests.exceptions")
            exc.HTTPError = type("HTTPError", (Exception,), {})
            req.exceptions = exc
            sys.modules["requests"] = req
            sys.modules["requests.exceptions"] = exc

    garth = _ensure_stub("garth")
    garth_exc = _ensure_stub("garth.exc", GarthHTTPError=type("GarthHTTPError", (Exception,), {}))
    garth.exc = garth_exc

    _ensure_stub("garminconnect",
                 Garmin=type("Garmin", (), {}),
                 GarminConnectAuthenticationError=type("GarminConnectAuthenticationError", (Exception,), {}))

    mcp = _ensure_stub("mcp")
    mserver = _ensure_stub("mcp.server")
    mfast = _ensure_stub("mcp.server.fastmcp", FastMCP=type("FastMCP", (), {}))
    mcp.server = mserver
    mserver.fastmcp = mfast

    import garmin_mcp
    return garmin_mcp


# --- shared auth guard -------------------------------------------------------
def test_authorized_open_when_no_key(gm, monkeypatch):
    monkeypatch.delenv("GARMIN_MCP_API_KEY", raising=False)
    assert gm._is_authorized({}) is True


def test_authorized_accepts_all_three_forms(gm, monkeypatch):
    monkeypatch.setenv("GARMIN_MCP_API_KEY", "k")
    assert gm._is_authorized({"headers": [(b"authorization", b"Bearer k")]}) is True
    assert gm._is_authorized({"headers": [(b"x-api-key", b"k")]}) is True
    assert gm._is_authorized({"query_string": b"api_key=k"}) is True


def test_authorized_rejects_wrong_key(gm, monkeypatch):
    monkeypatch.setenv("GARMIN_MCP_API_KEY", "k")
    assert gm._is_authorized({"headers": [(b"authorization", b"Bearer nope")]}) is False
    assert gm._is_authorized({}) is False


# --- offset resolution -------------------------------------------------------
def test_parse_offset_minutes(gm):
    assert gm._parse_offset_minutes("+02:00") == 120
    assert gm._parse_offset_minutes("-05:00") == -300
    assert gm._parse_offset_minutes("120") == 120
    assert gm._parse_offset_minutes("-90") == -90


def test_find_timezone_name(gm):
    assert gm._find_timezone_name({"a": {"timeZone": "Europe/Brussels"}}) == "Europe/Brussels"
    assert gm._find_timezone_name({"x": 1, "y": "no-slash"}) is None


def test_offset_env_override_wins(gm, monkeypatch):
    monkeypatch.setenv("GARMIN_HEALTH_EXPORT_UTC_OFFSET", "+02:00")
    assert gm.get_health_export_offset_minutes(object()) == 120


def test_offset_from_profile_timezone(gm, monkeypatch):
    monkeypatch.delenv("GARMIN_HEALTH_EXPORT_UTC_OFFSET", raising=False)
    monkeypatch.setattr(gm, "_health_export_offset_cache", {"value": None})

    class Real:
        def get_userprofile_settings(self):
            return {"userData": {"timeZone": "Etc/GMT-2"}}  # always UTC+2

    assert gm.get_health_export_offset_minutes(Real()) == 120


# --- disk-cache client proxy -------------------------------------------------
def test_cached_client_per_day_and_passthrough(gm, tmp_path, monkeypatch):
    monkeypatch.setattr(gm, "tokenstore", str(tmp_path))
    calls = []

    class Real:
        def get_hrv_data(self, d):
            calls.append(("hrv", d))
            return {"hrvReadings": []}

        def get_blood_pressure(self, s, e):
            calls.append(("bp", s, e))
            return {"measurementSummaries": []}

        def get_full_name(self):  # not a cached method -> passthrough
            return "Tim"

    c = gm._HealthExportCachedClient(Real())

    # Old date -> permanent cache: second call must be served from disk.
    assert c.get_hrv_data("2020-01-01") == {"hrvReadings": []}
    assert c.get_hrv_data("2020-01-01") == {"hrvReadings": []}
    assert calls.count(("hrv", "2020-01-01")) == 1

    # Range-based blood pressure is cached too.
    c.get_blood_pressure("2020-01-01", "2020-01-07")
    c.get_blood_pressure("2020-01-01", "2020-01-07")
    assert [x for x in calls if x[0] == "bp"] == [("bp", "2020-01-01", "2020-01-07")]

    # Unknown methods pass straight through to the real client.
    assert c.get_full_name() == "Tim"
