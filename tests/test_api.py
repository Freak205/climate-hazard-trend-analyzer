import httpx
import pytest

from conftest import THROUGH

Q = {"lat": 28.6, "lon": 77.2, "start_year": 1990, "end_year": 2020}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_analysis_shape_and_headline(client):
    r = client.get("/api/analysis", params=Q)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["hazard"] == "heatwave"
    assert body["region"]["grid_cell"] == {"lat": 28.5, "lon": 77.25}
    assert body["plot"]["years"][0] == 1990 and body["plot"]["years"][-1] == 2020
    assert set(body["trends"]) == {"frequency", "days", "mean_duration", "intensity"}
    # The synthetic series warms, so the honest headline should report a significant increase.
    assert "increased" in body["insights"]["headline"]
    assert body["trends"]["days"]["mann_kendall"]["trend"] == "increasing"
    assert len(body["trends"]["days"]["series"]["rolling_mean_5y"]) == 31
    assert "s-maxage" in r.headers["cache-control"]


def test_second_request_is_served_from_the_database(client, source):
    first = client.get("/api/analysis", params=Q).json()
    assert first["meta"]["cache"] == {"analysis": "miss", "raw": "miss"}
    second = client.get("/api/analysis", params={**Q, "start_year": 1995}).json()
    assert second["meta"]["cache"]["analysis"] == "hit"
    assert source.calls == 1


def test_nearby_points_share_one_grid_cell_cache(client, source):
    client.get("/api/analysis", params=Q)
    client.get("/api/analysis", params={**Q, "lat": 28.55, "lon": 77.28})
    assert source.calls == 1


def test_changing_params_reuses_raw_data(client, source):
    client.get("/api/analysis", params=Q)
    r = client.get("/api/analysis", params={**Q, "percentile": 90, "min_days": 4})
    assert r.json()["meta"]["cache"] == {"analysis": "miss", "raw": "hit"}
    assert source.calls == 1


def test_box_region_uses_centre(client):
    r = client.get("/api/analysis", params={"min_lat": 20, "max_lat": 30, "min_lon": 70, "max_lon": 80, "start_year": 1990, "end_year": 2020})
    assert r.status_code == 200
    assert r.json()["region"]["kind"] == "box" and r.json()["region"]["grid_cell"] == {"lat": 25.0, "lon": 75.0}


@pytest.mark.parametrize(
    "params",
    [
        {"lat": 95, "lon": 10},
        {"lat": 10, "lon": 200},
        {"lat": "abc", "lon": 10},
        {"lat": 10},
        {"lat": 10, "lon": 10, "min_lat": 1},
        {"min_lat": 10, "max_lat": 5, "min_lon": 0, "max_lon": 1},
        {"min_lat": -80, "max_lat": 80, "min_lon": -170, "max_lon": 170},
        {"lat": 10, "lon": 10, "start_year": 2020, "end_year": 1990},
        {"lat": 10, "lon": 10, "start_year": 2015, "end_year": 2020},   # < 10 years
        {"lat": 10, "lon": 10, "start_year": 1900, "end_year": 2000},
        {"lat": 10, "lon": 10, "end_year": THROUGH + 1},
        {"lat": 10, "lon": 10, "percentile": 12},
        {"lat": 10, "lon": 10, "min_days": 99},
        {"lat": 10, "lon": 10, "method": "x'; DROP TABLE"},
    ],
)
def test_bad_input_is_rejected_without_hitting_upstream(client, source, params):
    r = client.get("/api/analysis", params=params)
    assert r.status_code in (400, 422)
    assert "error" in r.json() and r.json()["error"]["message"]
    assert source.calls == 0


def test_unimplemented_hazard_is_a_clear_400(client):
    r = client.get("/api/analysis", params={**Q, "hazard": "drought"})
    assert r.status_code == 400 and "not implemented" in r.json()["error"]["message"]


def test_year_detail(client):
    r = client.get("/api/year", params={"lat": 28.6, "lon": 77.2, "year": 2010})
    assert r.status_code == 200
    b = r.json()
    assert len(b["dates"]) == len(b["tmax"]) == len(b["threshold"]) == len(b["in_heatwave"]) == 365
    assert b["in_heatwave"].count(True) == sum(e["duration"] for e in b["events"] if e["end"][:4] == "2010" and e["start"][:4] == "2010")


def test_csv_exports(client):
    r = client.get("/api/export", params={**Q, "dataset": "annual"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("year,valid") and len(lines) == 32
    r = client.get("/api/export", params={**Q, "dataset": "events"})
    assert r.text.startswith("start,end,duration_days")


def test_geocode_validates_and_caches(client, source):
    assert client.get("/api/geocode", params={"q": "a"}).status_code == 422
    assert client.get("/api/geocode", params={"q": "<script>alert(1)</script>"}).status_code == 400
    assert client.get("/api/geocode", params={"q": "Jaipur"}).json()["cache"] == "miss"
    assert client.get("/api/geocode", params={"q": "  jaipur "}).json()["cache"] == "hit"
    assert source.geo_calls == 1


def test_burst_rate_limit(service, settings):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from backend.app import create_app

    c = TestClient(create_app(service, replace(settings, rate_limit_per_minute=3)))
    codes = [c.get("/api/geocode", params={"q": "paris"}).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]
    r = c.get("/api/geocode", params={"q": "paris"})
    assert int(r.headers["retry-after"]) > 0


def test_ingest_rate_limit_only_counts_cache_misses(service, settings):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from backend.app import create_app

    c = TestClient(create_app(service, replace(settings, ingest_limit_per_hour=2)))
    ok = [c.get("/api/analysis", params={**Q, "lat": 10 + i}).status_code for i in range(3)]
    assert ok == [200, 200, 429]
    # cached cells keep working even though the budget is spent
    assert c.get("/api/analysis", params={**Q, "lat": 10}).status_code == 200


def test_upstream_failure_becomes_clean_502(service, settings, source):
    from fastapi.testclient import TestClient
    from backend.app import create_app
    from backend.errors import UpstreamUnavailable

    def boom(*a, **k):
        raise UpstreamUnavailable("Could not reach the weather data provider.")

    source.fetch_daily_tmax = boom
    c = TestClient(create_app(service, settings))
    r = c.get("/api/analysis", params=Q)
    assert r.status_code == 502 and "provider" in r.json()["error"]["message"]


def test_unhandled_errors_do_not_leak_details(service, settings, source):
    from fastapi.testclient import TestClient
    from backend.app import create_app

    source.fetch_daily_tmax = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret internals /etc/passwd"))
    c = TestClient(create_app(service, settings), raise_server_exceptions=False)
    r = c.get("/api/analysis", params=Q)
    assert r.status_code == 500 and "secret" not in r.text
