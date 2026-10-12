# Climate Hazard Trend Analyzer

A full-stack web app that answers one question honestly: **how have heatwaves changed in a place over time?**
Pick a city, state-centre or a custom lat/lon box, choose a period (e.g. 1990–2020), and get frequency /
duration / intensity time series, an interactive map and charts, and plain-language insights that say
"increased by X%" **only when a statistical test supports it**.

* **Frontend:** React 19 + TypeScript + Vite, Chart.js (charts), Leaflet (map region selection), jsPDF (PDF export)
* **Backend:** Python 3.12 + FastAPI, pure-stdlib statistics (no numpy/scipy needed)
* **Data:** Open-Meteo Historical Weather API (Copernicus **ERA5** reanalysis), daily max 2 m temperature, 1950 → last complete year
* **Database (NoSQL):** MongoDB (Atlas free tier works) when `MONGODB_URI` is set; a JSON-document store otherwise
* **Deploy target:** Vercel (static frontend + one Python serverless function)

> Live app: https://climate-hazard-trend-analyzer-one.vercel.app · Repo: https://github.com/Freak205/climate-hazard-trend-analyzer · Demo video (optional): not provided

---

## Quick start

```bash
# 1. backend
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn backend.app:create_app --factory --port 8000

# 2. frontend (second terminal)
cd frontend && npm ci && npm run dev                      # http://localhost:5173 (proxies /api -> :8000)

# tests
pytest                      # 67 backend tests (no network needed)
cd frontend && npm test     # frontend unit tests
```

Optional environment variables are listed in [.env.example](.env.example). With no configuration at all the app
runs fully (documents are cached as JSON files under `.data/`).

### Deploy to Vercel

```bash
npx vercel login
npx vercel deploy --prod
```

`vercel.json` already builds the frontend (`frontend/dist`), exposes `api/index.py` as the Python function
(60 s max duration) and rewrites `/api/*` to it. **To make the cache durable**, add a free MongoDB Atlas
cluster and set `MONGODB_URI` in the Vercel project settings (Settings → Environment Variables). Without it,
the document cache lives in the function instance's `/tmp` (see *Assumptions*).

---

## Architecture

```
 Browser (React)                              Vercel
┌───────────────────────┐   /api/*    ┌──────────────────────────────────────────────┐
│ Region picker         │ ──────────▶ │ FastAPI (api/index.py)                       │
│  search · presets ·   │             │  validation → rate limit → AnalysisService   │
│  Leaflet map & box    │             │                                              │
│ Controls (years,      │             │   ┌────────────── read-through ────────────┐ │
│  percentile, method)  │             │   │ analyses  (events, annual stats, QA)   │ │
│ Charts (Chart.js)     │ ◀────────── │   │      ▲ miss                            │ │
│ Insights · tables     │   JSON      │   │ raw_series (cleaned-input daily Tmax)  │ │      ┌───────────────┐
│ CSV / PDF export      │             │   │      ▲ miss                            │ │ ───▶ │ Open-Meteo    │
└───────────────────────┘             │   └─────────── MongoDB / JSON docs ────────┘ │      │ (ERA5 archive)│
                                      └──────────────────────────────────────────────┘      └───────────────┘
```

**Request flow for `GET /api/analysis`**

1. Validate inputs (ranges, enums, box size, years) → `400/422` before anything expensive happens.
2. Snap the point (or box centre) to the 0.25° ERA5 grid cell → this is the cache key.
3. Look up the `analyses` document for *(cell, method, percentile, min_days)* in the database.
4. On a miss, build it from the `raw_series` document for the cell; on a second miss, **ingest** 1950→last
   complete year from Open-Meteo (one request), store it, then clean → detect → store the analysis.
5. Slice the stored annual rows to the requested years and compute trend statistics (cheap) → JSON.

| Collection | Document | Notes |
|---|---|---|
| `raw_series` | one per ERA5 cell: daily Tmax as received (°C), metadata, `fetched_at` | TTL 90 days; also **seeded** (see below) |
| `analyses` | thresholds (366), every detected event, per-year metrics, data-quality report | derived; versioned (`ALGO_VERSION`) |
| `geocode` | cached city-search results | TTL 30 days |
| `rate_limits` | hourly counters for uncached (upstream-hitting) requests | TTL 2 h |

Layout: `backend/` (app, service, `climate/` heatwave + trends, cleaning, source client, `store/`),
`api/index.py` (Vercel entry), `frontend/src/` (components, API client), `shared/presets.json`
(preset places used by both sides), `seed/` (pre-fetched ERA5 docs), `scripts/seed_cache.py`, `tests/`.

### API

| Endpoint | Purpose |
|---|---|
| `GET /api/analysis` | Summary + trends + insights + plot series + events + data quality (JSON) |
| `GET /api/year?year=` | One year's daily Tmax vs threshold with heatwave days flagged (drives the "Year explorer") |
| `GET /api/export?dataset=annual\|events` | CSV download |
| `GET /api/geocode?q=` | City search (cached, rate limited) |
| `GET /api/config`, `/api/health` | Limits/defaults for the UI; liveness |

Region: `lat&lon` **or** `min_lat&min_lon&max_lat&max_lon`. Plus `start_year`, `end_year`, `hazard=heatwave`,
`percentile` (90, 92.5, 95, 97.5, 99), `min_days` (2–7), `method` (`calendar_day` | `fixed`).
Interactive docs at `/api/docs`.

---

## Hazard logic (heatwave)

**Definition (default):** a run of **≥ 3 consecutive days** whose daily maximum temperature is **strictly above
the 95th percentile** of that calendar day's baseline distribution.

* **Baseline = 1991–2020** (WMO standard normal). For each calendar day, the percentile is taken over a
  **±7-day window across all 30 baseline years (≈ 450 values)**, which removes the seasonal cycle: a "hot day"
  is hot *for the time of year*.
* **Thresholds never depend on the range the user picks.** Otherwise the yardstick would move with the window
  and trends would not be comparable between windows.
* Alternative `fixed` method: one regional percentile over all baseline days (the literal "95th percentile
  for that region"). In seasonal climates this only flags peak summer. Both are selectable in the UI.
* A missing day can never be a hot day and **breaks a run**. Events are attributed to the **year they start in**.
* Per-year metrics: **frequency** (events), **days** (heatwave days), **mean duration**, **intensity**
  (mean °C above threshold per heatwave day); events also carry peak °C and heat load (°C·days).

**Trend analysis** (over the selected years, on the annual series):

* **Mann–Kendall** (tie-corrected, continuity-corrected normal approximation) is the *deciding* test, because
  yearly counts are zero-inflated and non-normal.
* **Sen's slope** (median pairwise slope) and **OLS regression** (slope, R², t-test p-value) give the effect size.
* **5-year centred rolling mean** for the visual trend.
* Percent change compares the mean of the first vs. last ≤10 valid years, and is only quoted when the early
  mean > 0.

**Honest-insight rules** (`backend/insights.py`): the headline says *increased/decreased* only if Mann–Kendall
p < 0.05; otherwise it says "no statistically significant change" and shows the raw direction as a tendency.
Short windows, excluded years and the known limitations are always listed as caveats.
Example outputs from real data: Madrid 1990–2025 → *+261%, p = 0.0005*; Delhi 1990–2020 → *no significant
change (p = 0.25)* — the app reports both truthfully.

## Data handling (noisy real-world data)

`backend/cleaning.py`, with every step counted and shown in the UI's *Data quality* panel:

1. **Units** – the upstream unit string is read and converted to °C (°F/K handled), never assumed.
2. **Plausibility range** – values outside −90…60 °C become missing.
3. **Spike detection** – a value > 20 °C from the median of its ±7 neighbours becomes missing.
4. **Gaps** – ≤ 2 consecutive missing days are linearly interpolated; longer gaps stay missing.
5. **Coverage** – years with < 90 % valid days are flagged and **excluded from trends** (shown as `null`, not
   as "zero heatwaves").
6. **Payload validation** – structure/length checks, date alignment onto a contiguous daily array, bad cells → missing.
7. Local calendar day: requests use `timezone=auto`, so "daily max" is per local day.

## Security & performance

* **Input validation** everywhere (FastAPI/Pydantic bounds, enums, box ≤ 30° per side, years, geocode
  text whitelist). Errors are uniform JSON; unhandled exceptions never leak internals.
* **No SSRF surface:** only two hard-coded upstream hosts; user input reaches them only as validated numbers
  or a length-capped, whitelisted search string. Upstream calls have timeouts, bounded retries with
  back-off, `Retry-After` handling, a response-size cap and strict payload validation.
* **Rate limiting:** per-client per-minute budget (in-memory, per instance) + an hourly budget on *uncached*
  requests stored in the shared database (global when MongoDB is configured). Cache hits are never counted.
  Client IPs are hashed. `429` responses carry `Retry-After` and `X-RateLimit-*` headers.
* **Caching, three tiers:** database read-through cache (cell-level, so nearby clicks share data) → single-flight
  locks (concurrent identical requests share one upstream call) → CDN (`Cache-Control: s-maxage`).
* **Upstream budget protection:** a 75-year series costs ≈ 200 Open-Meteo "calls" against a 600/min free budget,
  so the preset cities/states ship **pre-seeded** (`seed/`, gzipped, ~30 KB each, regenerated with
  `python scripts/seed_cache.py`); everything else is fetched on demand. If the provider's budget is exhausted the
  API answers `503` with the wait time and the UI **retries automatically** after a countdown.
* **Headers:** CSP, `nosniff`, `X-Frame-Options: DENY`, HSTS, Permissions-Policy (see `vercel.json`);
  no `dangerouslySetInnerHTML`; shared-link parameters are parsed and sanitised.
* Graceful degradation: if MongoDB is unreachable the store falls back to the file cache instead of failing.

## Frontend

Region by **city search** (geocoder), **preset cities/states**, **map click** or **drawn box** (Leaflet) with
numeric fields; heatwave selected by default (drought / heavy rainfall appear as "coming soon");
year range with presets (min 10 years); advanced definition controls. Results: headline insight, four metric
tiles, bar chart + rolling mean + OLS/Theil–Sen trend (legend toggles; click a bar to inspect that year),
an event timeline, a **Year explorer** (daily Tmax vs threshold, heatwave days highlighted), trend statistics
table, sortable events table, data-quality panel, **CSV** and **PDF** export, and a shareable URL.
Colours follow a CVD-validated palette, support light/dark, charts have text alternatives and a table view.

## Assumptions & limitations

* ERA5 is a ~25 km **reanalysis**, not station data: it can differ from local stations and under-represents
  urban heat islands and extreme peaks.
* **A box is represented by the ERA5 cell at its centre**, and a **state/region by its centre point** (Open-Meteo's
  geocoder has no state boundaries). Area-averaging needs several upstream calls per request, which the free
  quota cannot support.
* Heatwaves are annual events attributed to their start year; for Southern-Hemisphere summers spanning
  December–February this splits the season across two calendar years.
* The last (partial) year is never analysed; the end of the range is the last complete ERA5 year.
* Mann–Kendall assumes independent years; autocorrelation is not corrected. 10 years is the enforced minimum
  window, and < 20 years always carries a caveat.
* **Persistence on Vercel:** the function filesystem is ephemeral (`/tmp`, per instance). Without `MONGODB_URI`
  the cache is therefore per-instance (cold starts recompute from the seed/upstream). I did not provision
  MongoDB Atlas on the author's behalf because it needs an account; the Mongo path is implemented and tested
  (against `mongomock`) and activates with one environment variable.
* Only heatwaves are implemented. The hazard registry, data model and API are shaped so droughts (SPI/SPEI) or
  heavy rainfall (R95p) could be added by ingesting precipitation and adding a detector.

## What I would improve with more time

* Area-averaged boxes / true state polygons (several ERA5 cells per request, with a paid or self-hosted
  Open-Meteo, or direct CDS/Zarr access).
* Excess Heat Factor (EHF) and wet-bulb/humid-heat metrics; station validation (NOAA GHCN-D).
* Mann–Kendall with autocorrelation correction (Hamed–Rao) and Bayesian/bootstrapped trend uncertainty bands.
* Drought (SPEI) and heavy-rain (R95p/Rx1day) hazards, and multi-region comparison.
* Provision MongoDB Atlas + a scheduled job to pre-warm popular cells; Playwright end-to-end tests in CI.

---

## AI tools used and how

* **Claude Code (Anthropic, model Claude Sonnet 5.5)** was used as the primary pair-programmer: it wrote the
  first drafts of the backend, the frontend, the tests and this README from the case-study brief, and ran the
  builds/tests/browser checks. Design decisions (percentile definition, fixed baseline, honest-insight rules,
  caching/seed strategy) were reasoned through and then verified by running the code against real ERA5 data
  (e.g. checking that ~5 % of baseline days exceed the 95th percentile, and that known-warming places such as
  Madrid, London and Phoenix show significant increases).
* Claude's `dataviz` skill guided the chart palette/accessibility choices.
* No AI-generated data is used anywhere: every number in the app comes from Open-Meteo/ERA5; the only synthetic
  series live in the unit tests and are labelled as such.

## Attribution

Weather data: [Open-Meteo.com](https://open-meteo.com/) (CC BY 4.0), contains modified Copernicus Climate Change
Service (ERA5) information. Map tiles © OpenStreetMap contributors.
