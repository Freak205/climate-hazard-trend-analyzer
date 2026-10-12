"""Data cleaning for noisy real-world daily temperature series.

Pipeline (each step is counted and reported back to the user as data quality):
  1. plausibility bounds   - values outside [-90, 60] C are physically impossible -> missing
  2. spike detection       - a day > 20 C away from the median of its +/-7 day neighbours -> missing
  3. short-gap fill        - runs of <= 2 missing days are linearly interpolated
  4. per-year coverage     - years with < 90 % valid days are flagged and excluded from trends

Longer gaps stay missing. Downstream, a missing day can never be part of a
heatwave and it breaks any run of consecutive hot days (conservative choice).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta

TEMP_MIN_C = -90.0
TEMP_MAX_C = 60.0
SPIKE_WINDOW = 7
SPIKE_THRESHOLD_C = 20.0
MAX_FILL_GAP = 2
MIN_YEAR_COVERAGE = 0.90


@dataclass
class CleanResult:
    values: list[float | None]
    quality: dict


def clean_series(raw: list[float | None], start: date) -> CleanResult:
    values = list(raw)
    n = len(values)
    missing_in = sum(v is None for v in values)

    # 1. plausibility
    out_of_range = 0
    for i, v in enumerate(values):
        if v is not None and not (TEMP_MIN_C <= v <= TEMP_MAX_C):
            values[i] = None
            out_of_range += 1

    # 2. isolated spikes (compare against neighbours, never against self)
    spikes: list[int] = []
    for i, v in enumerate(values):
        if v is None:
            continue
        lo, hi = max(0, i - SPIKE_WINDOW), min(n, i + SPIKE_WINDOW + 1)
        neigh = [x for j, x in enumerate(values[lo:hi], start=lo) if j != i and x is not None]
        if len(neigh) >= 5 and abs(v - statistics.median(neigh)) > SPIKE_THRESHOLD_C:
            spikes.append(i)
    for i in spikes:
        values[i] = None

    # 3. interpolate short gaps (only if both sides are valid)
    filled = 0
    i = 0
    while i < n:
        if values[i] is None:
            j = i
            while j < n and values[j] is None:
                j += 1
            gap = j - i
            if 0 < i and j < n and gap <= MAX_FILL_GAP:
                a, b = values[i - 1], values[j]
                for k in range(gap):
                    values[i + k] = round(a + (b - a) * (k + 1) / (gap + 1), 2)
                filled += gap
            i = j
        else:
            i += 1

    # 4. per-year coverage
    coverage: dict[int, float] = {}
    counts: dict[int, list[int]] = {}
    for idx, v in enumerate(values):
        y = (start + timedelta(days=idx)).year
        c = counts.setdefault(y, [0, 0])
        c[1] += 1
        c[0] += v is not None
    for y, (ok, total) in counts.items():
        coverage[y] = round(ok / total, 4)

    remaining_missing = sum(v is None for v in values)
    quality = {
        "total_days": n,
        "missing_in_source": missing_in,
        "out_of_range_removed": out_of_range,
        "spikes_removed": len(spikes),
        "gaps_interpolated_days": filled,
        "remaining_missing_days": remaining_missing,
        "valid_fraction": round(1 - remaining_missing / n, 4) if n else 0.0,
        "year_coverage": {str(y): c for y, c in sorted(coverage.items())},
        "low_coverage_years": sorted(y for y, c in coverage.items() if c < MIN_YEAR_COVERAGE),
        "rules": {
            "plausible_range_c": [TEMP_MIN_C, TEMP_MAX_C],
            "spike_threshold_c": SPIKE_THRESHOLD_C,
            "max_interpolated_gap_days": MAX_FILL_GAP,
            "min_year_coverage": MIN_YEAR_COVERAGE,
        },
    }
    return CleanResult(values, quality)
