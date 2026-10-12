"""FastAPI application: routes, input validation, error handling, security headers."""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Literal

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import exporting
from .config import (
    BASELINE_END,
    BASELINE_START,
    MIN_SPAN_YEARS,
    RAW_START_YEAR,
    Settings,
    get_settings,
    last_complete_year,
)
from .errors import ApiError, BadRequest
from .ratelimit import BurstLimiter, IngestLimiter, client_id
from .service import AnalysisService, HazardParams, Region, resolve_region
from .sources.open_meteo import OpenMeteoClient
from .store import build_store

log = logging.getLogger("climate.api")

PERCENTILES = (90.0, 92.5, 95.0, 97.5, 99.0)
MAX_BOX_SPAN_DEG = 30.0
QUERY_RE = re.compile(r"^[\w\s.,'’()\-]{2,60}$", re.UNICODE)

HAZARDS = [
    {"id": "heatwave", "label": "Heatwave", "available": True, "default": True,
     "description": "Consecutive days of exceptionally high daily maximum temperature."},
    {"id": "drought", "label": "Drought", "available": False, "default": False,
     "description": "Planned: SPI/SPEI-based dry spells (needs precipitation ingestion)."},
    {"id": "heavy_rain", "label": "Heavy rainfall", "available": False, "default": False,
     "description": "Planned: days above the 95th percentile of wet-day precipitation (R95p)."},
]

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
}


def create_app(service: AnalysisService | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if service is None:
        store = build_store(settings)
        service = AnalysisService(
            store,
            OpenMeteoClient(settings.upstream_timeout_seconds, settings.upstream_max_bytes),
            settings,
        )
    burst = BurstLimiter(settings.rate_limit_per_minute)
    ingest = IngestLimiter(service.store, settings.ingest_limit_per_hour)
    geo_ingest = IngestLimiter(service.store, settings.ingest_limit_per_hour * 10, bucket="geo")

    app = FastAPI(title="Climate Hazard Trend Analyzer", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.service = service
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["GET"],
        allow_headers=["Content-Type"],
        max_age=600,
    )

    # ------------------------------------------------------------ middleware
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    # ---------------------------------------------------------------- errors
    def err(status: int, code: str, message: str, retry_after: int | None = None, details=None) -> JSONResponse:
        body = {"error": {"code": code, "message": message}}
        if details:
            body["error"]["details"] = details
        headers = {"Retry-After": str(retry_after)} if retry_after else {}
        return JSONResponse(body, status_code=status, headers={**headers, "Cache-Control": "no-store"})

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError):
        return err(exc.status, exc.code, exc.message, exc.retry_after)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"][1:]), "problem": e["msg"][:120]} for e in exc.errors()[:8]]
        return err(422, "invalid_parameters", "One or more parameters are invalid.", details=details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        return err(exc.status_code, "http_error", "Not found." if exc.status_code == 404 else "Request failed.")

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("unhandled error")  # details go to logs, never to the client
        return err(500, "internal_error", "Something went wrong on our side.")

    # ----------------------------------------------------------- dependencies
    def limit(request: Request, response: Response) -> str:
        client = client_id(request)
        remaining, reset = burst.check(client)
        response.headers["X-RateLimit-Limit"] = str(settings.rate_limit_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset)
        return client

    def region_dep(
        lat: float | None = Query(None, ge=-90, le=90, description="Latitude of a point region"),
        lon: float | None = Query(None, ge=-180, le=180, description="Longitude of a point region"),
        min_lat: float | None = Query(None, ge=-90, le=90),
        min_lon: float | None = Query(None, ge=-180, le=180),
        max_lat: float | None = Query(None, ge=-90, le=90),
        max_lon: float | None = Query(None, ge=-180, le=180),
    ) -> Region:
        box_vals = (min_lat, min_lon, max_lat, max_lon)
        has_box = any(v is not None for v in box_vals)
        has_point = lat is not None or lon is not None
        if has_box and has_point:
            raise BadRequest("Provide either lat/lon or a min/max lat/lon box, not both.")
        if has_box:
            if any(v is None for v in box_vals):
                raise BadRequest("A box needs all of min_lat, min_lon, max_lat and max_lon.")
            if min_lat >= max_lat or min_lon >= max_lon:
                raise BadRequest("Box minimums must be smaller than maximums (boxes crossing the antimeridian are not supported).")
            if max_lat - min_lat > MAX_BOX_SPAN_DEG or max_lon - min_lon > MAX_BOX_SPAN_DEG:
                raise BadRequest(f"Box is too large; each side may span at most {MAX_BOX_SPAN_DEG:g} degrees.")
            return resolve_region(None, None, (min_lat, min_lon, max_lat, max_lon))
        if lat is None or lon is None:
            raise BadRequest("Provide lat and lon (point) or min_lat, min_lon, max_lat, max_lon (box).")
        return resolve_region(lat, lon, None)

    def params_dep(
        hazard: Literal["heatwave", "drought", "heavy_rain"] = Query("heatwave"),
        percentile: float = Query(95.0, description="One of 90, 92.5, 95, 97.5, 99"),
        min_days: int = Query(3, ge=2, le=7),
        method: Literal["calendar_day", "fixed"] = Query("calendar_day"),
    ) -> HazardParams:
        if hazard != "heatwave":
            raise BadRequest(f"The '{hazard}' hazard is not implemented yet; only 'heatwave' is available.")
        if percentile not in PERCENTILES:
            raise BadRequest(f"percentile must be one of {', '.join(f'{p:g}' for p in PERCENTILES)}.")
        return HazardParams(percentile, min_days, method)

    def years_dep(
        start_year: int = Query(1990, ge=RAW_START_YEAR, le=2100),
        end_year: int = Query(2020, ge=RAW_START_YEAR, le=2100),
    ) -> tuple[int, int]:
        if start_year > end_year:
            raise BadRequest("start_year must not be after end_year.")
        return start_year, end_year

    def cache_headers(response: Response, long: bool = True) -> None:
        # Let Vercel's CDN absorb repeat reads; stale-while-revalidate keeps it snappy.
        response.headers["Cache-Control"] = "public, s-maxage=3600, stale-while-revalidate=86400" if long else "public, s-maxage=300"

    # ----------------------------------------------------------------- routes
    @app.get("/api/health")
    def health():
        return {"status": "ok", "store": service.store.name, "data_through_year": last_complete_year()}

    @app.get("/api/config")
    def config(response: Response):
        cache_headers(response)
        through = last_complete_year()
        return {
            "hazards": HAZARDS,
            "percentiles": list(PERCENTILES),
            "methods": [
                {"id": "calendar_day", "label": "Calendar-day percentile (±7 day window)"},
                {"id": "fixed", "label": "Single regional percentile"},
            ],
            "min_days": {"min": 2, "max": 7, "default": 3},
            "years": {"min": RAW_START_YEAR, "max": through, "min_span": MIN_SPAN_YEARS, "default_start": 1990, "default_end": min(2020, through)},
            "baseline": {"start_year": BASELINE_START, "end_year": BASELINE_END},
            "max_box_span_deg": MAX_BOX_SPAN_DEG,
        }

    @app.get("/api/geocode")
    def geocode(response: Response, q: str = Query(..., min_length=2, max_length=60), client: str = Depends(limit)):
        q = " ".join(q.split())
        if not QUERY_RE.match(q):
            raise BadRequest("Search text contains unsupported characters.")
        results, status = service.search_places(q, on_upstream=lambda: geo_ingest.check(client))
        cache_headers(response)
        return {"query": q, "results": results, "cache": status}

    @app.get("/api/analysis")
    def analysis(
        response: Response,
        region: Region = Depends(region_dep),
        params: HazardParams = Depends(params_dep),
        years: tuple[int, int] = Depends(years_dep),
        client: str = Depends(limit),
    ):
        result = service.summary(region, params, years[0], years[1], on_ingest=lambda: ingest.check(client))
        cache_headers(response)
        return result

    @app.get("/api/year")
    def year_detail(
        response: Response,
        year: int = Query(..., ge=RAW_START_YEAR, le=2100),
        region: Region = Depends(region_dep),
        params: HazardParams = Depends(params_dep),
        client: str = Depends(limit),
    ):
        result = service.year_detail(region, params, year, on_ingest=lambda: ingest.check(client))
        cache_headers(response)
        return result

    @app.get("/api/export")
    def export(
        dataset: Literal["annual", "events"] = Query("annual"),
        region: Region = Depends(region_dep),
        params: HazardParams = Depends(params_dep),
        years: tuple[int, int] = Depends(years_dep),
        client: str = Depends(limit),
    ):
        data = service.summary(region, params, years[0], years[1], on_ingest=lambda: ingest.check(client))
        if dataset == "annual":
            doc, _ = service.get_analysis(region, params)
            rows = [r for r in doc["annual"] if years[0] <= r["year"] <= years[1]]
            body = exporting.annual_csv(data, rows)
        else:
            body = exporting.events_csv(data["events"])
        name = f"heatwave_{dataset}_{region.lat:+.2f}_{region.lon:+.2f}_{years[0]}-{years[1]}.csv"
        return Response(
            body,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "public, s-maxage=3600"},
        )

    return app
