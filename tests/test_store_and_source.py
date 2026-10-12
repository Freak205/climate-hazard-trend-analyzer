import time
from datetime import date

import httpx
import mongomock
import pytest

from backend.errors import UpstreamRateLimited, UpstreamUnavailable
from backend.sources.open_meteo import OpenMeteoClient, parse_archive_payload
from backend.store.file_store import FileStore
from backend.store.mongo_store import MongoStore


@pytest.fixture(params=["file", "mongo"])
def store(request, tmp_path):
    if request.param == "file":
        return FileStore(str(tmp_path))
    return MongoStore("mongodb://unused", "test", client=mongomock.MongoClient(tz_aware=True))


def test_store_roundtrip_and_expiry(store):
    store.put("c", "a/b:c", {"x": [1, None, 2.5]}, 60)
    assert store.get("c", "a/b:c") == {"x": [1, None, 2.5]}
    assert store.get("c", "missing") is None
    store.put("c", "old", {"x": 1}, -1)
    assert store.get("c", "old") is None


def test_store_overwrite(store):
    store.put("c", "k", {"v": 1}, 60)
    store.put("c", "k", {"v": 2}, 60)
    assert store.get("c", "k") == {"v": 2}


def test_store_counter(store):
    assert [store.incr("rl", "k", 60) for _ in range(3)] == [1, 2, 3]
    assert store.incr("rl", "other", 60) == 1


def test_file_store_rejects_path_traversal_ids(tmp_path):
    s = FileStore(str(tmp_path / "root"))
    s.put("../evil", "../../x", {"a": 1}, 60)
    assert s.get("../evil", "../../x") == {"a": 1}
    assert not (tmp_path / "x.json").exists()
    assert all(str(p).startswith(str(tmp_path / "root")) for p in (tmp_path / "root").rglob("*.json"))


# -------------------------------------------------------------- upstream parsing
def payload(times, temps, units="°C"):
    return {"latitude": 10.0, "longitude": 20.0, "elevation": 5.0, "timezone": "UTC",
            "daily_units": {"temperature_2m_max": units}, "daily": {"time": times, "temperature_2m_max": temps}}


def test_parse_aligns_gaps_and_bad_values():
    p = payload(["2000-01-01", "2000-01-02", "2000-01-04"], [10.0, None, "n/a"])
    s = parse_archive_payload(p, date(2000, 1, 1), date(2000, 1, 5))
    assert s.values == [10.0, None, None, None, None]


def test_parse_converts_fahrenheit():
    s = parse_archive_payload(payload(["2000-01-01"], [212.0], "°F"), date(2000, 1, 1), date(2000, 1, 1))
    assert s.values == [100.0]


def test_parse_rejects_garbage():
    with pytest.raises(UpstreamUnavailable):
        parse_archive_payload({"daily": {}}, date(2000, 1, 1), date(2000, 1, 2))
    with pytest.raises(UpstreamUnavailable):
        parse_archive_payload(payload(["2000-01-01"], [1.0, 2.0]), date(2000, 1, 1), date(2000, 1, 2))
    with pytest.raises(UpstreamUnavailable):
        parse_archive_payload(payload(["2000-01-01"], [None]), date(2000, 1, 1), date(2000, 1, 1))


def make_client(handler, **kw):
    return OpenMeteoClient(transport=httpx.MockTransport(handler), **kw)


def test_429_maps_to_rate_limited_without_retrying():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429, headers={"Retry-After": "42"}, json={})

    with pytest.raises(UpstreamRateLimited) as ei:
        make_client(handler).fetch_daily_tmax(1, 1, date(2000, 1, 1), date(2000, 1, 2))
    assert ei.value.retry_after == 42 and len(calls) == 1


def test_5xx_is_retried_then_succeeds(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=payload(["2000-01-01"], [3.0]))

    s = make_client(handler).fetch_daily_tmax(1, 1, date(2000, 1, 1), date(2000, 1, 1))
    assert s.values == [3.0] and len(calls) == 3


def test_oversized_response_is_rejected(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    big = httpx.Response(200, content=b"x" * 5000)
    with pytest.raises(UpstreamUnavailable):
        make_client(lambda r: big, max_bytes=1000).fetch_daily_tmax(1, 1, date(2000, 1, 1), date(2000, 1, 1))


def test_request_only_goes_to_fixed_hosts_with_numeric_params():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json=payload(["2000-01-01"], [3.0]))

    make_client(handler).fetch_daily_tmax(12.3456789, -45.5, date(2000, 1, 1), date(2000, 1, 1))
    assert seen[0].url.host == "archive-api.open-meteo.com" and "latitude=12.3457" in str(seen[0].url)


def test_minutely_and_hourly_limits_advertise_different_waits():
    def run(reason):
        client = make_client(lambda r: httpx.Response(429, json={"error": True, "reason": reason}))
        with pytest.raises(UpstreamRateLimited) as ei:
            client.fetch_daily_tmax(1, 1, date(2000, 1, 1), date(2000, 1, 2))
        return ei.value

    assert run("Minutely API request limit exceeded. Please try again in one minute.").retry_after == 60
    hourly = run("Hourly API request limit exceeded. Please try again in the next hour.")
    assert hourly.retry_after == 3600 and "hourly" in hourly.message


def test_seed_layer_serves_prefetched_docs_without_writing(tmp_path):
    from backend.store.seed_store import SeededStore, write_seed

    seeds = tmp_path / "seed"
    write_seed(seeds, "raw_series", "era5-tmax|+10.00_+20.00|1950-2025", {"values": [1.0, None]})
    primary = FileStore(str(tmp_path / "data"))
    store = SeededStore(primary, str(seeds))
    assert store.get("raw_series", "era5-tmax|+10.00_+20.00|1950-2025") == {"values": [1.0, None]}
    assert store.get("raw_series", "other") is None
    assert store.get("analyses", "era5-tmax|+10.00_+20.00|1950-2025") is None  # only raw series are seeded
    assert primary.get("raw_series", "era5-tmax|+10.00_+20.00|1950-2025") is None  # never copied/written
    store.put("raw_series", "x", {"a": 1}, 60)
    assert store.get("raw_series", "x") == {"a": 1}
