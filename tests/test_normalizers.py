from health_export.normalizers import (
    normalize_hrv,
    normalize_spo2,
    normalize_respiration,
    normalize_resting_hr,
    normalize_vo2max,
    normalize_blood_pressure,
    normalize_hydration,
)


# --- HRV ---------------------------------------------------------------------
def test_hrv_uses_granular_readings_when_present():
    raw = {
        "hrvReadings": [
            {"readingTimeGMT": "2026-06-07T01:14:00.0", "hrvValue": 42},
            {"readingTimeGMT": "2026-06-07T01:19:00.0", "hrvValue": 45},
        ],
        "hrvSummary": {"lastNightAvg": 44},
    }
    out = normalize_hrv(raw, offset_minutes=120)
    assert out == [
        {"time": "2026-06-07T03:14:00+02:00", "rmssd_ms": 42.0, "granularity": "reading"},
        {"time": "2026-06-07T03:19:00+02:00", "rmssd_ms": 45.0, "granularity": "reading"},
    ]


def test_hrv_falls_back_to_daily_avg():
    raw = {"hrvReadings": [], "hrvSummary": {"lastNightAvg": 44, "weeklyAvg": 40,
            "createTimeStamp": "2026-06-07T05:00:00.0"}}
    out = normalize_hrv(raw, offset_minutes=120)
    assert out == [
        {"time": "2026-06-07T07:00:00+02:00", "rmssd_ms": 44.0, "granularity": "daily"},
    ]


def test_hrv_empty_returns_empty():
    assert normalize_hrv({}, offset_minutes=0) == []


def test_hrv_derives_offset_from_gmt_local_pair():
    # GMT 01:14 + local 03:14 implies +02:00; fallback (0) must be ignored.
    raw = {"hrvReadings": [{"readingTimeGMT": "2026-06-07T01:14:00.0",
                            "readingTimeLocal": "2026-06-07T03:14:00.0",
                            "hrvValue": 42}]}
    out = normalize_hrv(raw, offset_minutes=0)
    assert out == [{"time": "2026-06-07T03:14:00+02:00", "rmssd_ms": 42.0,
                    "granularity": "reading"}]


# --- SpO2 --------------------------------------------------------------------
def test_spo2_maps_single_values():
    raw = {"spO2HourlyAverages": None,
           "spO2SingleValues": [[1780794840000, 96], [1780795140000, 95]]}
    out = normalize_spo2(raw, offset_minutes=120)
    assert out == [
        {"time": "2026-06-07T03:14:00+02:00", "percent": 96},
        {"time": "2026-06-07T03:19:00+02:00", "percent": 95},
    ]


def test_spo2_falls_back_to_hourly_averages():
    raw = {"spO2SingleValues": None, "spO2HourlyAverages": [[1780794840000, 96]]}
    out = normalize_spo2(raw, offset_minutes=120)
    assert out == [{"time": "2026-06-07T03:14:00+02:00", "percent": 96}]


def test_spo2_skips_null_and_negative_sentinel():
    raw = {"spO2SingleValues": [[1780794840000, None], [1780794840000, -1], [1780795140000, 95]]}
    out = normalize_spo2(raw, offset_minutes=120)
    assert out == [{"time": "2026-06-07T03:19:00+02:00", "percent": 95}]


def test_spo2_empty():
    assert normalize_spo2({}, 0) == []
    assert normalize_spo2(None, 0) == []


def test_spo2_derives_offset_from_top_level_pair():
    # Top-level start GMT/local implies +02:00; reading epoch is 01:14Z -> 03:14.
    raw = {"startTimestampGMT": "2026-06-07T00:00:00.0",
           "startTimestampLocal": "2026-06-07T02:00:00.0",
           "spO2SingleValues": [[1780794840000, 96]]}
    out = normalize_spo2(raw, offset_minutes=0)
    assert out == [{"time": "2026-06-07T03:14:00+02:00", "percent": 96}]


# --- Respiration -------------------------------------------------------------
def test_respiration_maps_pairs():
    raw = {"respirationValuesArray": [[1780794840000, 14], [1780795140000, 15.5]]}
    out = normalize_respiration(raw, offset_minutes=120)
    assert out == [
        {"time": "2026-06-07T03:14:00+02:00", "breaths_per_min": 14.0},
        {"time": "2026-06-07T03:19:00+02:00", "breaths_per_min": 15.5},
    ]


def test_respiration_skips_negative_sentinel():
    raw = {"respirationValuesArray": [[1780794840000, -2], [1780795140000, 15]]}
    out = normalize_respiration(raw, offset_minutes=120)
    assert out == [{"time": "2026-06-07T03:19:00+02:00", "breaths_per_min": 15.0}]


# --- Resting HR --------------------------------------------------------------
def test_resting_hr_daily_value():
    raw = {"restingHeartRate": 52}
    out = normalize_resting_hr(raw, date="2026-06-07", offset_minutes=120)
    assert out == [{"date": "2026-06-07", "time": "2026-06-07T00:00:00+02:00", "bpm": 52}]


def test_resting_hr_nested_allmetrics():
    raw = {"allMetrics": {"metricsMap": {"WELLNESS_RESTING_HEART_RATE": [{"value": 49}]}}}
    out = normalize_resting_hr(raw, date="2026-06-07", offset_minutes=0)
    assert out == [{"date": "2026-06-07", "time": "2026-06-07T00:00:00+00:00", "bpm": 49}]


def test_resting_hr_missing():
    assert normalize_resting_hr({}, date="2026-06-07", offset_minutes=0) == []


# --- VO2max ------------------------------------------------------------------
def test_vo2max_unwraps_list_and_maps_sports():
    # get_max_metrics returns a list-wrapped dict
    raw = [{"generic": {"vo2MaxPreciseValue": 48.2},
            "cycling": {"vo2MaxPreciseValue": 52.0}}]
    out = normalize_vo2max(raw, date="2026-06-07", offset_minutes=120)
    assert out == [
        {"date": "2026-06-07", "time": "2026-06-07T00:00:00+02:00", "value": 48.2, "sport": "running"},
        {"date": "2026-06-07", "time": "2026-06-07T00:00:00+02:00", "value": 52.0, "sport": "cycling"},
    ]


def test_vo2max_bare_dict_still_supported():
    raw = {"generic": {"vo2MaxValue": 50}}
    out = normalize_vo2max(raw, date="2026-06-07", offset_minutes=0)
    assert out == [{"date": "2026-06-07", "time": "2026-06-07T00:00:00+00:00",
                    "value": 50.0, "sport": "running"}]


def test_vo2max_missing_or_nondict():
    assert normalize_vo2max({}, date="2026-06-07", offset_minutes=0) == []
    assert normalize_vo2max([], date="2026-06-07", offset_minutes=0) == []
    assert normalize_vo2max(None, date="2026-06-07", offset_minutes=0) == []
    assert normalize_vo2max("No max metrics data found", date="2026-06-07", offset_minutes=0) == []


# --- Blood pressure ----------------------------------------------------------
def test_blood_pressure_maps_measurements():
    raw = {"measurementSummaries": [
        {"measurements": [
            {"measurementTimestampLocal": "2026-06-07T08:01:00.0",
             "systolic": 120, "diastolic": 80, "pulse": 60},
            {"measurementTimestampLocal": "2026-06-07T20:30:00.0",
             "systolic": 118, "diastolic": 79, "pulse": None},
        ]}
    ]}
    out = normalize_blood_pressure(raw, offset_minutes=120)
    assert out == [
        {"time": "2026-06-07T08:01:00+02:00", "systolic": 120, "diastolic": 80, "pulse": 60},
        {"time": "2026-06-07T20:30:00+02:00", "systolic": 118, "diastolic": 79, "pulse": None},
    ]


def test_blood_pressure_derives_offset_from_pair():
    # GMT 06:01 + local 08:01 implies +02:00; fallback (0) ignored.
    raw = {"measurementSummaries": [{"measurements": [
        {"measurementTimestampGMT": "2026-06-07T06:01:00.0",
         "measurementTimestampLocal": "2026-06-07T08:01:00.0",
         "systolic": 120, "diastolic": 80, "pulse": 60},
    ]}]}
    out = normalize_blood_pressure(raw, offset_minutes=0)
    assert out == [{"time": "2026-06-07T08:01:00+02:00", "systolic": 120,
                    "diastolic": 80, "pulse": 60}]


def test_blood_pressure_empty():
    assert normalize_blood_pressure({"measurementSummaries": []}, 0) == []


# --- Hydration ---------------------------------------------------------------
def test_hydration_daily_total_spans_day():
    raw = {"valueInML": 1500}
    out = normalize_hydration(raw, date="2026-06-07", offset_minutes=120)
    assert out == [{
        "date": "2026-06-07",
        "start": "2026-06-07T00:00:00+02:00",
        "end": "2026-06-07T23:59:59+02:00",
        "volume_ml": 1500,
    }]


def test_hydration_zero_or_missing_skipped():
    assert normalize_hydration({"valueInML": 0}, date="2026-06-07", offset_minutes=0) == []
    assert normalize_hydration({}, date="2026-06-07", offset_minutes=0) == []
