"""CSV export of the insight datasets (numbers and ISO dates only, so no
spreadsheet-formula injection surface)."""
from __future__ import annotations

import csv
import io

ANNUAL_COLUMNS = ["year", "valid", "heatwave_events", "heatwave_days", "mean_duration_days", "intensity_c_above_threshold", "longest_event_days"]
EVENT_COLUMNS = ["start", "end", "duration_days", "peak_tmax_c", "mean_tmax_c", "mean_excess_c", "max_excess_c", "heat_load_degree_days"]


def annual_csv(summary: dict, annual_rows: list[dict]) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(ANNUAL_COLUMNS)
    for r in annual_rows:
        w.writerow([r["year"], int(r["valid"]), r["frequency"], r["days"], r["mean_duration"], r["intensity"], r["longest"]])
    return out.getvalue()


def events_csv(events: list[dict]) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(EVENT_COLUMNS)
    for e in events:
        w.writerow([e["start"], e["end"], e["duration"], e["peak_c"], e["mean_c"], e["mean_excess_c"], e["max_excess_c"], e["heat_load"]])
    return out.getvalue()
