"""Open-Meteo client (ERA5 reanalysis archive + geocoding).

Safe-access rules enforced here:
  * only two fixed, hard-coded hosts are ever contacted (no user-supplied URLs -> no SSRF)
  * all user input reaches the upstream only as validated numbers / a length-capped query
  * hard timeouts, bounded retries with backoff, Retry-After respected on 429
  * response size is capped while streaming; the payload is structurally validated
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import httpx

from ..errors import UpstreamRateLimited, UpstreamUnavailable

log = logging.getLogger("climate.source")

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
SOURCE_NAME = "Open-Meteo Historical Weather API (ERA5 reanalysis, daily max 2 m temperature)"
MAX_ATTEMPTS = 3


@dataclass
class RawSeries:
    start: date
    values: list[float | None]  # degrees Celsius, None = missing in the upstream payload
    grid_lat: float
    grid_lon: float
    elevation: float | None
    timezone: str | None
    units_original: str


def _to_celsius(units: str) -> tuple[float, float]:
    """Return (scale, offset) such that celsius = value * scale + offset."""
    u = units.replace("°", "").replace("Â", "").strip().upper()
    if u in ("C", "CELSIUS", ""):
        return 1.0, 0.0
    if u in ("F", "FAHRENHEIT"):
        return 5.0 / 9.0, -32.0 * 5.0 / 9.0
    if u in ("K", "KELVIN"):
        return 1.0, -273.15
    raise UpstreamUnavailable("Upstream returned an unrecognised temperature unit.")


def _reason(resp: httpx.Response) -> str:
    try:
        return str(json.loads(resp.read()).get("reason", ""))[:160]
    except Exception:
        return ""


def _rate_limited(resp: httpx.Response, reason: str | None = None) -> UpstreamRateLimited:
    """Open-Meteo has minutely / hourly / daily budgets; tell the client how long to wait."""
    reason = (reason if reason is not None else _reason(resp)).lower()
    header = int(resp.headers.get("Retry-After", "0") or 0)
    if "minute" in reason:
        wait, scope = max(header, 60), "per-minute"
    elif "hour" in reason:
        wait, scope = max(header, 3600), "hourly"
    elif "day" in reason or "daily" in reason:
        wait, scope = max(header, 3600), "daily"
    else:
        wait, scope = header or 60, "request"
    return UpstreamRateLimited(
        f"The weather data provider's {scope} request budget is used up. Places already in our database still work instantly.",
        retry_after=wait,
    )


class OpenMeteoClient:
    def __init__(self, timeout: float = 20.0, max_bytes: int = 8 * 1024 * 1024, transport: httpx.BaseTransport | None = None):
        self.max_bytes = max_bytes
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=6.0),
            transport=transport,
            headers={"User-Agent": "climate-hazard-trend-analyzer/1.0 (case-study)"},
            follow_redirects=False,
        )

    # ------------------------------------------------------------------ http
    def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        last: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                with self._client.stream("GET", url, params=params) as resp:
                    if resp.status_code == 429:
                        raise _rate_limited(resp)
                    if resp.status_code >= 500:
                        raise UpstreamUnavailable(f"Weather data provider error ({resp.status_code}).")
                    if resp.status_code >= 400:
                        reason = _reason(resp)
                        if "limit exceeded" in reason.lower():
                            raise _rate_limited(resp, reason)
                        raise UpstreamUnavailable(f"Weather data provider rejected the request: {reason or resp.status_code}")
                    body = bytearray()
                    for chunk in resp.iter_bytes():
                        body.extend(chunk)
                        if len(body) > self.max_bytes:
                            raise UpstreamUnavailable("Upstream response exceeded the size limit.")
                    return json.loads(body)
            except UpstreamRateLimited:
                raise  # retrying immediately only burns more quota
            except (httpx.TransportError, UpstreamUnavailable, json.JSONDecodeError) as exc:
                last = exc
                log.warning("upstream attempt %d/%d failed: %s", attempt, MAX_ATTEMPTS, type(exc).__name__)
                if attempt < MAX_ATTEMPTS:
                    time.sleep(0.4 * (3 ** (attempt - 1)))
        if isinstance(last, UpstreamUnavailable):
            raise last
        raise UpstreamUnavailable("Could not reach the weather data provider.")

    # --------------------------------------------------------------- archive
    def fetch_daily_tmax(self, lat: float, lon: float, start: date, end: date) -> RawSeries:
        payload = self._get_json(
            ARCHIVE_URL,
            {
                "latitude": f"{lat:.4f}",
                "longitude": f"{lon:.4f}",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "daily": "temperature_2m_max",
                "temperature_unit": "celsius",
                "models": "era5",
                "timezone": "auto",  # aggregate to the local calendar day
            },
        )
        return parse_archive_payload(payload, start, end)

    # -------------------------------------------------------------- geocoding
    def search_places(self, query: str, count: int = 6) -> list[dict[str, Any]]:
        payload = self._get_json(
            GEOCODE_URL, {"name": query, "count": count, "language": "en", "format": "json"}
        )
        out = []
        for row in payload.get("results") or []:
            try:
                out.append(
                    {
                        "name": str(row["name"])[:80],
                        "admin1": str(row.get("admin1") or "")[:80],
                        "country": str(row.get("country") or "")[:80],
                        "lat": float(row["latitude"]),
                        "lon": float(row["longitude"]),
                        "population": row.get("population"),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue  # skip malformed rows rather than failing the whole search
        return out


def parse_archive_payload(payload: dict[str, Any], start: date, end: date) -> RawSeries:
    """Validate the payload and align it onto a contiguous daily array."""
    try:
        daily = payload["daily"]
        times = daily["time"]
        temps = daily["temperature_2m_max"]
        units = str(payload.get("daily_units", {}).get("temperature_2m_max", "°C"))
        grid_lat, grid_lon = float(payload["latitude"]), float(payload["longitude"])
    except (KeyError, TypeError, ValueError):
        raise UpstreamUnavailable("Unexpected response shape from the weather data provider.") from None
    if not isinstance(times, list) or not isinstance(temps, list) or len(times) != len(temps):
        raise UpstreamUnavailable("Inconsistent time/temperature arrays from the weather data provider.")

    scale, offset = _to_celsius(units)
    n_days = (end - start).days + 1
    values: list[float | None] = [None] * n_days
    for t, v in zip(times, temps):
        try:
            idx = (date.fromisoformat(t) - start).days
        except (TypeError, ValueError):
            continue
        if 0 <= idx < n_days and isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
            values[idx] = round(float(v) * scale + offset, 2)
    if all(v is None for v in values):
        raise UpstreamUnavailable("The weather data provider returned no usable temperatures for this location.")
    return RawSeries(
        start=start,
        values=values,
        grid_lat=grid_lat,
        grid_lon=grid_lon,
        elevation=payload.get("elevation") if isinstance(payload.get("elevation"), (int, float)) else None,
        timezone=payload.get("timezone") if isinstance(payload.get("timezone"), str) else None,
        units_original=units,
    )


def day_range(start: date, n: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]
