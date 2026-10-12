"""Central configuration. Everything tunable comes from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

# Raw ERA5 history is ingested from this year; ERA5 starts in 1940 but 1950 is
# the start of the consistent satellite-era record and keeps payloads small.
RAW_START_YEAR = 1950
# WMO standard climatological normal, used as the percentile reference period.
BASELINE_START = 1991
BASELINE_END = 2020
MIN_SPAN_YEARS = 10
# ERA5 native resolution; coordinates are snapped to this grid so that nearby
# requests share one cache entry (and the key space is bounded).
GRID_STEP = 0.25
# ERA5 lags real time by ~5 days, so a year is "complete" only a bit after Dec 31.
ERA5_LAG_DAYS = 10


def last_complete_year(today: date | None = None) -> int:
    today = today or date.today()
    return today.year - 1 if (today - date(today.year, 1, 1)).days >= ERA5_LAG_DAYS else today.year - 2


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    mongodb_uri: str | None
    mongodb_db: str
    data_dir: str
    raw_ttl_seconds: int
    analysis_ttl_seconds: int
    geocode_ttl_seconds: int
    rate_limit_per_minute: int
    ingest_limit_per_hour: int
    upstream_timeout_seconds: float
    upstream_max_bytes: int
    allowed_origins: tuple[str, ...]
    seed_dir: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    on_vercel = bool(os.environ.get("VERCEL"))
    origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return Settings(
        mongodb_uri=os.environ.get("MONGODB_URI") or None,
        mongodb_db=os.environ.get("MONGODB_DB", "climate_hazards"),
        # Vercel's filesystem is read-only except /tmp (which is per-instance).
        data_dir=os.environ.get("DATA_DIR", "/tmp/climate-cache" if on_vercel else ".data"),
        raw_ttl_seconds=_int("RAW_TTL_SECONDS", 60 * 60 * 24 * 90),
        analysis_ttl_seconds=_int("ANALYSIS_TTL_SECONDS", 60 * 60 * 24 * 30),
        geocode_ttl_seconds=_int("GEOCODE_TTL_SECONDS", 60 * 60 * 24 * 30),
        rate_limit_per_minute=_int("RATE_LIMIT_PER_MINUTE", 90),
        ingest_limit_per_hour=_int("INGEST_LIMIT_PER_HOUR", 8),
        upstream_timeout_seconds=float(os.environ.get("UPSTREAM_TIMEOUT_SECONDS", 20)),
        upstream_max_bytes=_int("UPSTREAM_MAX_BYTES", 8 * 1024 * 1024),
        allowed_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
        seed_dir=os.environ.get("SEED_DIR", str(Path(__file__).resolve().parent.parent / "seed")),
    )
