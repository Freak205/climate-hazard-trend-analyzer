import math
import os
import random
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.config import RAW_START_YEAR, Settings, last_complete_year  # noqa: E402
from backend.sources.open_meteo import RawSeries  # noqa: E402


def synthetic_values(start: date, end: date, warming_per_year: float = 0.04, seed: int = 7) -> list[float]:
    """Seasonal cycle + noise + linear warming: a series whose heatwaves should increase."""
    rng = random.Random(seed)
    noise = 0.0  # AR(1) noise: real daily temperatures are strongly autocorrelated
    out = []
    d = start
    while d <= end:
        doy = d.timetuple().tm_yday
        base = 27 + 9 * math.sin(2 * math.pi * (doy - 110) / 365.25)
        noise = 0.8 * noise + rng.gauss(0, 1.8)
        out.append(round(base + warming_per_year * (d.year - 1990) + noise, 1))
        d += timedelta(days=1)
    return out


class FakeSource:
    """Stands in for Open-Meteo: counts calls, never touches the network."""

    def __init__(self, warming: float = 0.04):
        self.calls = 0
        self.geo_calls = 0
        self.warming = warming

    def fetch_daily_tmax(self, lat, lon, start, end):
        self.calls += 1
        return RawSeries(start, synthetic_values(start, end, self.warming), lat, lon, 100.0, "UTC", "°C")

    def search_places(self, query, count=6):
        self.geo_calls += 1
        return [{"name": query.title(), "admin1": "Test", "country": "Testland", "lat": 10.0, "lon": 20.0, "population": 1}]


@pytest.fixture
def settings(tmp_path):
    return Settings(
        mongodb_uri=None, mongodb_db="t", data_dir=str(tmp_path / "data"),
        raw_ttl_seconds=3600, analysis_ttl_seconds=3600, geocode_ttl_seconds=3600,
        rate_limit_per_minute=1000, ingest_limit_per_hour=50,
        upstream_timeout_seconds=5, upstream_max_bytes=8_000_000, allowed_origins=("http://localhost:5173",),
    )


@pytest.fixture
def source():
    return FakeSource()


@pytest.fixture
def service(settings, source):
    from backend.service import AnalysisService
    from backend.store.file_store import FileStore

    return AnalysisService(FileStore(settings.data_dir), source, settings)


@pytest.fixture
def client(service, settings):
    from fastapi.testclient import TestClient
    from backend.app import create_app

    return TestClient(create_app(service, settings), raise_server_exceptions=False)


THROUGH = last_complete_year()
__all__ = ["synthetic_values", "FakeSource", "THROUGH", "RAW_START_YEAR"]
