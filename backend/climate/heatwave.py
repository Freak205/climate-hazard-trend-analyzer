"""Heatwave definition and detection.

Definition (follows the ETCCDI / WMO-style percentile approach):

  A heatwave is a run of >= ``min_days`` consecutive days on which daily maximum
  temperature is strictly above that day's threshold.

Two threshold methods are supported:

  calendar_day (default)  the ``percentile`` of baseline-period (1991-2020) Tmax
                          for that calendar day, pooled over a +/-7 day window
                          (15 days x 30 years = 450 values). This removes the
                          seasonal cycle so a 'hot day' is hot *for the season*.
  fixed                   a single ``percentile`` of all baseline Tmax values in
                          the region (the literal reading of "95th percentile for
                          that region"). In seasonal climates this only ever
                          flags the hottest part of summer.

Thresholds are always derived from the fixed baseline period, never from the
user-selected range, so the 'hotness' yardstick does not move when the user
changes the window and trends are comparable across windows.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Sequence

from ..config import BASELINE_END, BASELINE_START
from ..errors import InsufficientData

# Cumulative days before each month in a leap year -> a leap-year-independent
# calendar-day index (0..365) so 29 Feb has its own slot.
_CUM = [0, 31, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
HALF_WINDOW = 7
MIN_BASELINE_VALID_FRACTION = 0.70
MIN_SAMPLES_PER_DAY = 100


def doy_index(d: date) -> int:
    return _CUM[d.month - 1] + d.day - 1


def percentile(sorted_values: Sequence[float], pct: float) -> float:
    """Linear-interpolation percentile (same as numpy's default)."""
    n = len(sorted_values)
    if n == 1:
        return float(sorted_values[0])
    k = (n - 1) * pct / 100.0
    lo = int(k)
    hi = min(lo + 1, n - 1)
    return float(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo))


def compute_thresholds(
    values: Sequence[float | None],
    start: date,
    pct: float,
    method: str = "calendar_day",
    baseline: tuple[int, int] = (BASELINE_START, BASELINE_END),
) -> list[float | None]:
    """Return 366 thresholds indexed by calendar day (see ``doy_index``)."""
    buckets: list[list[float]] = [[] for _ in range(366)]
    n_baseline_days = n_valid = 0
    for i, v in enumerate(values):
        d = start + timedelta(days=i)
        if not (baseline[0] <= d.year <= baseline[1]):
            continue
        n_baseline_days += 1
        if v is not None:
            n_valid += 1
            buckets[doy_index(d)].append(v)

    if n_baseline_days == 0 or n_valid / n_baseline_days < MIN_BASELINE_VALID_FRACTION:
        raise InsufficientData(
            f"Not enough valid data in the {baseline[0]}-{baseline[1]} baseline period to define heatwave thresholds."
        )

    if method == "fixed":
        pooled = sorted(v for b in buckets for v in b)
        return [percentile(pooled, pct)] * 366

    thresholds: list[float | None] = []
    for d in range(366):
        pool: list[float] = []
        for off in range(-HALF_WINDOW, HALF_WINDOW + 1):
            pool.extend(buckets[(d + off) % 366])
        if len(pool) < MIN_SAMPLES_PER_DAY:
            thresholds.append(None)
        else:
            pool.sort()
            thresholds.append(round(percentile(pool, pct), 2))
    return thresholds


def detect_events(
    values: Sequence[float | None],
    start: date,
    thresholds: Sequence[float | None],
    min_days: int = 3,
) -> list[dict]:
    """Find every run of >= min_days consecutive exceedance days."""
    events: list[dict] = []
    run: list[tuple[int, float, float]] = []  # (day index, tmax, excess)

    def close() -> None:
        if len(run) >= min_days:
            first, last = run[0][0], run[-1][0]
            s, e = start + timedelta(days=first), start + timedelta(days=last)
            temps = [r[1] for r in run]
            excess = [r[2] for r in run]
            events.append(
                {
                    "start": s.isoformat(),
                    "end": e.isoformat(),
                    "year": s.year,  # an event belongs to the year it started in
                    "duration": len(run),
                    "peak_c": round(max(temps), 1),
                    "mean_c": round(sum(temps) / len(temps), 1),
                    "mean_excess_c": round(sum(excess) / len(excess), 2),
                    "max_excess_c": round(max(excess), 1),
                    "heat_load": round(sum(excess), 1),  # cumulative degree-days above threshold
                }
            )
        run.clear()

    for i, v in enumerate(values):
        thr = thresholds[doy_index(start + timedelta(days=i))] if v is not None else None
        if v is not None and thr is not None and v > thr:
            run.append((i, v, v - thr))
        else:  # a hot day is required on every day of the run: gaps break it
            close()
    close()
    return events


def annual_stats(
    events: Sequence[dict],
    first_year: int,
    last_year: int,
    year_coverage: dict[str, float],
    min_coverage: float,
) -> list[dict]:
    """Per-year hazard metrics. Years with poor data coverage are marked invalid
    (metrics null) rather than reported as 'zero heatwaves'."""
    by_year: dict[int, list[dict]] = {}
    for ev in events:
        by_year.setdefault(ev["year"], []).append(ev)

    rows = []
    for y in range(first_year, last_year + 1):
        coverage = year_coverage.get(str(y), 0.0)
        valid = coverage >= min_coverage
        evs = by_year.get(y, [])
        days = sum(e["duration"] for e in evs)
        row = {
            "year": y,
            "valid": valid,
            "coverage": coverage,
            "frequency": len(evs) if valid else None,
            "days": days if valid else None,
            "mean_duration": round(days / len(evs), 2) if valid and evs else None,
            "intensity": round(sum(e["heat_load"] for e in evs) / days, 2) if valid and evs else None,
            "longest": max((e["duration"] for e in evs), default=0) if valid else None,
        }
        rows.append(row)
    return rows
