from datetime import date, timedelta

import pytest

from backend.climate import heatwave
from backend.cleaning import clean_series
from backend.errors import InsufficientData
from conftest import synthetic_values

START, END = date(1950, 1, 1), date(2022, 12, 31)


def idx(d: date) -> int:
    return (d - START).days


def test_percentile_matches_numpy_default():
    assert heatwave.percentile([1, 2, 3, 4, 5], 95) == pytest.approx(4.8)
    assert heatwave.percentile([10], 50) == 10


def test_doy_index_has_leap_day_slot():
    assert heatwave.doy_index(date(2000, 2, 29)) == 59
    assert heatwave.doy_index(date(2001, 3, 1)) == 60
    assert heatwave.doy_index(date(2001, 12, 31)) == 365


def flat_thresholds(value=30.0):
    return [value] * 366


def series_with(hot_days: list[date], hot=35.0, normal=20.0):
    vals = [normal] * ((date(2000, 12, 31) - START).days + 1)
    for d in hot_days:
        vals[idx(d)] = hot
    return vals


def test_three_consecutive_hot_days_is_a_heatwave_two_is_not():
    hot = [date(2000, 6, 1) + timedelta(days=i) for i in range(3)] + [date(2000, 7, 1) + timedelta(days=i) for i in range(2)]
    events = heatwave.detect_events(series_with(hot), START, flat_thresholds(), 3)
    assert len(events) == 1
    assert events[0]["start"] == "2000-06-01" and events[0]["duration"] == 3
    assert events[0]["mean_excess_c"] == 5.0 and events[0]["heat_load"] == 15.0


def test_threshold_is_strict_inequality():
    vals = series_with([date(2000, 6, d) for d in (1, 2, 3)], hot=30.0)
    assert heatwave.detect_events(vals, START, flat_thresholds(30.0), 3) == []


def test_missing_day_breaks_a_run():
    days = [date(2000, 6, d) for d in (1, 2, 3, 4, 5)]
    vals = series_with(days)
    vals[idx(date(2000, 6, 3))] = None
    events = heatwave.detect_events(vals, START, flat_thresholds(), 3)
    assert events == []  # 2 + 2 days, never 3 consecutive valid hot days


def test_event_year_is_start_year_and_event_can_span_new_year():
    days = [date(1999, 12, 30) + timedelta(days=i) for i in range(4)]
    events = heatwave.detect_events(series_with(days), START, flat_thresholds(), 3)
    assert events[0]["year"] == 1999 and events[0]["end"] == "2000-01-02"


def test_calendar_day_threshold_follows_the_season():
    vals = synthetic_values(START, END, warming_per_year=0.0)
    thr = heatwave.compute_thresholds(vals, START, 95)
    summer = thr[heatwave.doy_index(date(2000, 4, 20))]  # sinusoid peak ~ day 201
    winter = thr[heatwave.doy_index(date(2000, 1, 20))]
    assert summer is not None and winter is not None and summer > winter + 8


def test_fixed_threshold_is_constant_and_higher_than_winter_calendar_day():
    vals = synthetic_values(START, END, warming_per_year=0.0)
    fixed = heatwave.compute_thresholds(vals, START, 95, "fixed")
    assert len(set(fixed)) == 1
    cal = heatwave.compute_thresholds(vals, START, 95, "calendar_day")
    assert fixed[0] > cal[heatwave.doy_index(date(2000, 1, 20))]


def test_about_five_percent_of_baseline_days_exceed_p95():
    vals = synthetic_values(START, END, warming_per_year=0.0)
    thr = heatwave.compute_thresholds(vals, START, 95)
    n = hot = 0
    for i, v in enumerate(vals):
        d = START + timedelta(days=i)
        if 1991 <= d.year <= 2020:
            n += 1
            hot += v > thr[heatwave.doy_index(d)]
    assert 0.04 < hot / n < 0.06


def test_insufficient_baseline_raises():
    vals = [None] * ((END - START).days + 1)
    with pytest.raises(InsufficientData):
        heatwave.compute_thresholds(vals, START, 95)


def test_warming_series_produces_more_heatwave_days_later():
    vals = synthetic_values(START, END, warming_per_year=0.05)
    thr = heatwave.compute_thresholds(vals, START, 95)
    events = heatwave.detect_events(vals, START, thr, 3)
    early = sum(e["duration"] for e in events if e["year"] < 1980)
    late = sum(e["duration"] for e in events if e["year"] >= 1993)
    assert late > early * 2


def test_annual_stats_marks_low_coverage_years_invalid():
    rows = heatwave.annual_stats([], 2000, 2001, {"2000": 1.0, "2001": 0.5}, 0.9)
    assert rows[0]["valid"] and rows[0]["frequency"] == 0
    assert not rows[1]["valid"] and rows[1]["frequency"] is None


# ------------------------------------------------------------------ cleaning
def test_cleaning_handles_gaps_outliers_and_spikes():
    start = date(2000, 1, 1)
    vals = [20.0 + (i % 5) * 0.2 for i in range(60)]
    vals[10] = None            # single gap -> interpolated
    vals[20] = None
    vals[21] = None            # 2-day gap -> interpolated
    for i in (30, 31, 32):     # 3-day gap -> stays missing
        vals[i] = None
    vals[40] = 99.0            # impossible -> removed
    vals[50] = 45.0            # 25 C spike versus neighbours -> removed
    res = clean_series(vals, start)
    q = res.quality
    assert q["out_of_range_removed"] == 1 and q["spikes_removed"] == 1
    # 3 source gap days + the 2 removed outlier days (single-day gaps) are interpolated
    assert q["gaps_interpolated_days"] == 5
    assert res.values[10] is not None and res.values[20] is not None
    assert res.values[30] is None and q["remaining_missing_days"] == 3
    assert 19 < res.values[40] < 22 and 19 < res.values[50] < 22  # bad readings never survive
