from health_export.service import build_bundle


class FakeClient:
    def get_hrv_data(self, d):
        return {"hrvReadings": [{"readingTimeGMT": "2026-06-07T01:14:00.0", "hrvValue": 42}]}

    def get_spo2_data(self, d):
        return {"spO2SingleValues": [[1780794840000, 96]]}

    def get_respiration_data(self, d):
        return {"respirationValuesArray": [[1780794840000, 14]]}

    def get_rhr_day(self, d):
        return {"restingHeartRate": 52}

    def get_max_metrics(self, d):
        return [{"generic": {"vo2MaxPreciseValue": 48.2}}]

    def get_blood_pressure(self, s, e):
        return {"measurementSummaries": []}

    def get_hydration_data(self, d):
        return {"valueInML": 1500}


def test_build_bundle_single_day_all_types():
    b = build_bundle(FakeClient(), "2026-06-07", "2026-06-07", offset_minutes=120, types=None)
    assert b["start"] == "2026-06-07" and b["end"] == "2026-06-07"
    assert b["hrv"][0]["rmssd_ms"] == 42.0
    assert b["spo2"][0]["percent"] == 96
    assert b["resting_hr"][0]["bpm"] == 52
    assert b["vo2max"][0]["value"] == 48.2
    assert b["hydration"][0]["volume_ml"] == 1500
    assert b["blood_pressure"] == []
    assert b["errors"] == []


def test_build_bundle_collects_per_type_error_and_continues():
    class Boom(FakeClient):
        def get_spo2_data(self, d):
            raise RuntimeError("garmin 500")

    b = build_bundle(Boom(), "2026-06-07", "2026-06-07", offset_minutes=0, types=None)
    assert b["spo2"] == []
    assert any(e["type"] == "spo2" and "garmin 500" in e["message"] for e in b["errors"])
    assert b["hrv"]  # other types still present


def test_build_bundle_types_filter():
    b = build_bundle(FakeClient(), "2026-06-07", "2026-06-07", offset_minutes=0, types=["hrv"])
    assert b["hrv"]
    assert b["spo2"] == [] and b["resting_hr"] == []


def test_build_bundle_multi_day_accumulates():
    b = build_bundle(FakeClient(), "2026-06-06", "2026-06-08", offset_minutes=0, types=["resting_hr"])
    # one resting-hr record per day in the inclusive range
    assert len(b["resting_hr"]) == 3
    assert [r["date"] for r in b["resting_hr"]] == ["2026-06-06", "2026-06-07", "2026-06-08"]
