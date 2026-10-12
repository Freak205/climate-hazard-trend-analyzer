"""Orchestration: ingest -> clean -> detect -> store -> read -> summarise.

Data flow
---------
  raw_series  (collection)  one document per 0.25 deg ERA5 cell: the cleaned-inputs
                            (raw daily Tmax 1950..last complete year, as received)
  analyses    (collection)  one document per (cell, threshold method, percentile,
                            min_days): thresholds, every detected event, annual stats,
                            data-quality report
  API calls read `analyses` from the database; on a miss they build it from
  `raw_series`, and on a miss there they ingest from Open-Meteo first
  (read-through cache). Trend statistics for the *selected year range* are cheap
  and computed per request from the stored annual rows.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from .climate import heatwave, trends
from .cleaning import MIN_YEAR_COVERAGE, clean_series
from .config import (
    BASELINE_END,
    BASELINE_START,
    GRID_STEP,
    MIN_SPAN_YEARS,
    RAW_START_YEAR,
    Settings,
    last_complete_year,
)
from .errors import BadRequest
from .insights import METRICS, build_insights
from .sources.open_meteo import SOURCE_NAME, OpenMeteoClient
from .store.base import DocumentStore

ALGO_VERSION = 2  # bump to invalidate stored analyses when detection logic changes
MAX_EVENTS_RETURNED = 600

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


@dataclass(frozen=True)
class Region:
    """A request region resolved to the single ERA5 grid cell that represents it."""

    lat: float
    lon: float
    kind: str  # "point" | "box"
    center_lat: float
    center_lon: float
    box: tuple[float, float, float, float] | None = None  # min_lat, min_lon, max_lat, max_lon

    @property
    def cell_id(self) -> str:
        return f"{self.lat:+.2f}_{self.lon:+.2f}"


def snap(value: float) -> float:
    return round(round(value / GRID_STEP) * GRID_STEP, 2)


def resolve_region(lat: float | None, lon: float | None, box: tuple[float, float, float, float] | None) -> Region:
    if box is not None:
        min_lat, min_lon, max_lat, max_lon = box
        c_lat, c_lon = (min_lat + max_lat) / 2, (min_lon + max_lon) / 2
        kind = "box"
    else:
        assert lat is not None and lon is not None
        c_lat, c_lon, kind = lat, lon, "point"
    return Region(
        lat=max(-90.0, min(90.0, snap(c_lat))),
        lon=snap(c_lon),
        kind=kind,
        center_lat=round(c_lat, 4),
        center_lon=round(c_lon, 4),
        box=box,
    )


@dataclass(frozen=True)
class HazardParams:
    percentile: float = 95.0
    min_days: int = 3
    method: str = "calendar_day"

    @property
    def key(self) -> str:
        return f"{self.method}|p{self.percentile:g}|d{self.min_days}"


class AnalysisService:
    def __init__(self, store: DocumentStore, source: OpenMeteoClient, settings: Settings):
        self.store, self.source, self.settings = store, source, settings

    # ------------------------------------------------------------------ raw
    def get_raw(self, region: Region, on_ingest: Callable[[], None] | None = None) -> tuple[dict, str]:
        through = last_complete_year()
        doc_id = f"era5-tmax|{region.cell_id}|{RAW_START_YEAR}-{through}"
        doc = self.store.get("raw_series", doc_id)
        if doc is not None:
            return doc, "hit"
        with _lock_for(doc_id):  # single-flight: concurrent identical requests share one upstream call
            doc = self.store.get("raw_series", doc_id)
            if doc is not None:
                return doc, "hit"
            if on_ingest:
                on_ingest()
            start, end = date(RAW_START_YEAR, 1, 1), date(through, 12, 31)
            series = self.source.fetch_daily_tmax(region.lat, region.lon, start, end)
            doc = {
                "_id": doc_id,
                "source": SOURCE_NAME,
                "cell": {
                    "lat": region.lat,
                    "lon": region.lon,
                    "grid_lat": series.grid_lat,
                    "grid_lon": series.grid_lon,
                    "elevation_m": series.elevation,
                    "timezone": series.timezone,
                },
                "units_original": series.units_original,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "through_year": through,
                "values": series.values,
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            self.store.put("raw_series", doc_id, doc, self.settings.raw_ttl_seconds)
            return doc, "miss"

    # ------------------------------------------------------------- analysis
    def get_analysis(self, region: Region, params: HazardParams, on_ingest: Callable[[], None] | None = None) -> tuple[dict, dict]:
        through = last_complete_year()
        doc_id = f"heatwave|{region.cell_id}|{RAW_START_YEAR}-{through}|{params.key}|b{BASELINE_START}-{BASELINE_END}|v{ALGO_VERSION}"
        doc = self.store.get("analyses", doc_id)
        if doc is not None:
            return doc, {"analysis": "hit", "raw": "hit"}
        with _lock_for(doc_id):
            doc = self.store.get("analyses", doc_id)
            if doc is not None:
                return doc, {"analysis": "hit", "raw": "hit"}
            raw, raw_status = self.get_raw(region, on_ingest)
            doc = self._compute_analysis(raw, params)
            self.store.put("analyses", doc_id, doc, self.settings.analysis_ttl_seconds)
            return doc, {"analysis": "miss", "raw": raw_status}

    @staticmethod
    def _compute_analysis(raw: dict, params: HazardParams) -> dict:
        start = date.fromisoformat(raw["start"])
        cleaned = clean_series(raw["values"], start)
        thresholds = heatwave.compute_thresholds(cleaned.values, start, params.percentile, params.method)
        events = heatwave.detect_events(cleaned.values, start, thresholds, params.min_days)
        annual = heatwave.annual_stats(
            events, RAW_START_YEAR, raw["through_year"], cleaned.quality["year_coverage"], MIN_YEAR_COVERAGE
        )
        base_rows = [r for r in annual if BASELINE_START <= r["year"] <= BASELINE_END and r["valid"]]
        reference = {
            "period": [BASELINE_START, BASELINE_END],
            **{
                k: round(sum(r[k] for r in base_rows if r[k] is not None) / max(1, sum(r[k] is not None for r in base_rows)), 2)
                for k in ("frequency", "days", "mean_duration", "intensity")
            },
        }
        return {
            "raw_id": raw["_id"],
            "cell": raw["cell"],
            "source": raw["source"],
            "through_year": raw["through_year"],
            "params": {"percentile": params.percentile, "min_days": params.min_days, "method": params.method},
            "thresholds": thresholds,
            "events": events,
            "annual": annual,
            "reference": reference,
            "quality": cleaned.quality,
            "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    # ---------------------------------------------------------------- views
    def validate_years(self, start_year: int, end_year: int) -> None:
        through = last_complete_year()
        if start_year < RAW_START_YEAR or end_year > through:
            raise BadRequest(f"Years must be between {RAW_START_YEAR} and {through}.")
        if end_year - start_year + 1 < MIN_SPAN_YEARS:
            raise BadRequest(f"Choose at least {MIN_SPAN_YEARS} years: trends over shorter windows are not meaningful.")

    def summary(self, region: Region, params: HazardParams, start_year: int, end_year: int,
                on_ingest: Callable[[], None] | None = None) -> dict:
        self.validate_years(start_year, end_year)
        doc, cache = self.get_analysis(region, params, on_ingest)

        rows = [r for r in doc["annual"] if start_year <= r["year"] <= end_year]
        years = [r["year"] for r in rows]
        metric_values = {k: [r[k] for r in rows] for k in METRICS}
        trend = {k: trends.analyse_metric(years, metric_values[k]) for k in METRICS}
        insights = build_insights(trend, start_year, end_year)

        excluded = [r["year"] for r in rows if not r["valid"]]
        if excluded:
            insights["caveats"].insert(
                0, f"Years excluded for poor data coverage (<{int(MIN_YEAR_COVERAGE * 100)}% valid days): {', '.join(map(str, excluded))}."
            )

        events = [e for e in doc["events"] if start_year <= e["year"] <= end_year]
        valid_rows = [r for r in rows if r["valid"]]
        summary = {
            "total_events": len(events),
            "total_heatwave_days": sum(e["duration"] for e in events),
            "longest_event": max(events, key=lambda e: e["duration"], default=None),
            "most_intense_event": max(events, key=lambda e: e["mean_excess_c"], default=None),
            "peak_temperature": max(events, key=lambda e: e["peak_c"], default=None),
            "years_analysed": len(valid_rows),
            "years_excluded": excluded,
        }
        return {
            "hazard": "heatwave",
            "region": {
                "kind": region.kind,
                "requested_center": {"lat": region.center_lat, "lon": region.center_lon},
                "box": None if region.box is None else dict(zip(("min_lat", "min_lon", "max_lat", "max_lon"), region.box)),
                "grid_cell": {"lat": region.lat, "lon": region.lon},
                "elevation_m": doc["cell"].get("elevation_m"),
                "timezone": doc["cell"].get("timezone"),
                "note": "Box regions are represented by the ERA5 grid cell at their centre." if region.kind == "box" else None,
            },
            "params": {**doc["params"], "start_year": start_year, "end_year": end_year},
            "definition": (
                f"{doc['params']['min_days']}+ consecutive days with daily maximum temperature above the "
                f"{doc['params']['percentile']:g}th percentile of "
                + ("each calendar day's" if params.method == "calendar_day" else "all")
                + f" {BASELINE_START}–{BASELINE_END} baseline values"
                + (" (±7-day window)" if params.method == "calendar_day" else " in the region")
            ),
            "baseline": {"start_year": BASELINE_START, "end_year": BASELINE_END},
            "reference": doc["reference"],
            "summary": summary,
            "insights": insights,
            "trends": trend,
            "plot": {
                "years": years,
                "valid": [r["valid"] for r in rows],
                "metrics": {k: metric_values[k] for k in METRICS},
                "metric_meta": METRICS,
            },
            "events": events[-MAX_EVENTS_RETURNED:],
            "events_truncated": len(events) > MAX_EVENTS_RETURNED,
            "data_quality": {k: v for k, v in doc["quality"].items() if k != "year_coverage"}
            | {"year_coverage": {str(y): doc["quality"]["year_coverage"].get(str(y)) for y in years}},
            "meta": {
                "source": doc["source"],
                "data_through_year": doc["through_year"],
                "cache": cache,
                "store": self.store.name,
                "computed_at": doc["computed_at"],
            },
        }

    def year_detail(self, region: Region, params: HazardParams, year: int,
                    on_ingest: Callable[[], None] | None = None) -> dict:
        through = last_complete_year()
        if not (RAW_START_YEAR <= year <= through):
            raise BadRequest(f"Year must be between {RAW_START_YEAR} and {through}.")
        doc, cache = self.get_analysis(region, params, on_ingest)
        raw, _ = self.get_raw(region, on_ingest)
        start = date.fromisoformat(raw["start"])
        cleaned = clean_series(raw["values"], start).values
        first = (date(year, 1, 1) - start).days
        n = (date(year, 12, 31) - date(year, 1, 1)).days + 1
        dates = [(date(year, 1, 1) + timedelta(days=i)) for i in range(n)]
        tmax = cleaned[first:first + n]
        thr = [doc["thresholds"][heatwave.doy_index(d)] for d in dates]
        in_hw = [False] * n
        for e in doc["events"]:
            s, en = date.fromisoformat(e["start"]), date.fromisoformat(e["end"])
            if s.year > year or en.year < year:
                continue
            for k in range(max(0, (s - dates[0]).days), min(n, (en - dates[0]).days + 1)):
                in_hw[k] = True
        return {
            "year": year,
            "dates": [d.isoformat() for d in dates],
            "tmax": tmax,
            "threshold": thr,
            "in_heatwave": in_hw,
            "events": [e for e in doc["events"] if e["year"] == year],
            "meta": {"cache": cache},
        }

    # --------------------------------------------------------------- places
    def search_places(self, query: str, on_upstream: Callable[[], None] | None = None) -> tuple[list[dict], str]:
        key = " ".join(query.lower().split())
        doc = self.store.get("geocode", key)
        if doc is not None:
            return doc["results"], "hit"
        if on_upstream:
            on_upstream()
        results = self.source.search_places(query)
        self.store.put("geocode", key, {"results": results}, self.settings.geocode_ttl_seconds)
        return results, "miss"
