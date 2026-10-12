import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiClientError, fetchAnalysis, fetchConfig, fetchYear } from './api'
import { RegionPicker, boxIsValid, regionSummary } from './components/RegionPicker'
import { Results } from './components/Results'
import { parseQuery, queryToSearch } from './urlState'
import type { Analysis, AppConfig, Method, Query, Region, YearDetail } from './types'

const DEFAULT_REGION: Region = { kind: 'point', lat: 28.61, lon: 77.21, label: 'Delhi, India' }

function bestYear(a: Analysis): number {
  const { years, valid, metrics } = a.plot
  let best = years[years.length - 1]
  let bestV = -1
  years.forEach((y, i) => {
    const v = metrics.days[i]
    if (valid[i] && v !== null && v > bestV) { bestV = v; best = y }
  })
  return best
}

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [configError, setConfigError] = useState<string | null>(null)

  // draft = what the controls show; applied = what the results were computed for
  const [region, setRegion] = useState<Region>(DEFAULT_REGION)
  const [startYear, setStartYear] = useState(1990)
  const [endYear, setEndYear] = useState(2020)
  const [percentile, setPercentile] = useState(95)
  const [minDays, setMinDays] = useState(3)
  const [method, setMethod] = useState<Method>('calendar_day')

  const [applied, setApplied] = useState<Query | null>(null)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [year, setYear] = useState<number | null>(null)
  const [yearDetail, setYearDetail] = useState<YearDetail | null>(null)
  const [yearLoading, setYearLoading] = useState(false)
  const [yearError, setYearError] = useState<string | null>(null)

  const runCtl = useRef<AbortController | null>(null)
  const [retryIn, setRetryIn] = useState<number | null>(null)
  const retryQuery = useRef<Query | null>(null)

  const run = useCallback((q: Query) => {
    runCtl.current?.abort()
    const ctl = new AbortController()
    runCtl.current = ctl
    setLoading(true)
    setError(null)
    setRetryIn(null)
    fetchAnalysis(q, ctl.signal)
      .then((a) => {
        setAnalysis(a)
        setApplied(q)
        setYear(bestYear(a))
        history.replaceState(null, '', queryToSearch(q))
      })
      .catch((e: Error) => {
        if (e.name === 'AbortError') return
        if (e instanceof ApiClientError && e.code === 'upstream_rate_limited' && (e.retryAfter ?? 999) <= 90) {
          // Per-minute provider budget: wait it out and retry automatically (once the countdown ends).
          retryQuery.current = q
          setRetryIn(Math.max(5, e.retryAfter ?? 60))
        }
        const retry = e instanceof ApiClientError && e.retryAfter && e.retryAfter > 90 ? ` (try again in ~${Math.ceil(e.retryAfter / 60)} min)` : ''
        setError(e.message + retry)
      })
      .finally(() => { if (runCtl.current === ctl) setLoading(false) })
  }, [])

  useEffect(() => {
    if (retryIn === null) return
    if (retryIn <= 0) {
      const q = retryQuery.current
      setRetryIn(null)
      if (q) run(q)
      return
    }
    const t = setTimeout(() => setRetryIn((n) => (n === null ? null : n - 1)), 1000)
    return () => clearTimeout(t)
  }, [retryIn, run])

  // bootstrap: config, then URL state or defaults
  useEffect(() => {
    const ctl = new AbortController()
    fetchConfig(ctl.signal)
      .then((c) => {
        setConfig(c)
        const fromUrl = parseQuery(window.location.search, c)
        const q: Query = fromUrl ?? { region: DEFAULT_REGION, startYear: c.years.default_start, endYear: c.years.default_end, percentile: 95, minDays: c.min_days.default, method: 'calendar_day' }
        setRegion(q.region); setStartYear(q.startYear); setEndYear(q.endYear)
        setPercentile(q.percentile); setMinDays(q.minDays); setMethod(q.method)
        run(q)
      })
      .catch((e: Error) => { if (e.name !== 'AbortError') setConfigError(e.message) })
    return () => ctl.abort()
  }, [run])

  // year explorer follows the selected year
  useEffect(() => {
    if (!applied || year === null) return
    const ctl = new AbortController()
    setYearLoading(true)
    setYearError(null)
    fetchYear(applied, year, ctl.signal)
      .then((d) => { setYearDetail(d); setYearLoading(false) })
      .catch((e: Error) => { if (e.name !== 'AbortError') { setYearError(e.message); setYearLoading(false) } })
    return () => ctl.abort()
  }, [applied, year])

  const span = endYear - startYear + 1
  const yearsOk = !!config && startYear <= endYear && span >= config.years.min_span
  const regionOk = !!config && boxIsValid(region, config.max_box_span_deg)
  const canRun = yearsOk && regionOk && !loading

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (canRun) run({ region, startYear, endYear, percentile, minDays, method })
  }

  const yearOptions = config ? Array.from({ length: config.years.max - config.years.min + 1 }, (_, i) => config.years.min + i) : []

  return (
    <div className="wrap">
      <header className="top">
        <h1>Climate Hazard Trend Analyzer</h1>
        <p>How have heatwaves changed where you live? Pick a place and a period to see frequency, duration and intensity trends, based on 70+ years of ERA5 reanalysis data and a percentile-based definition.</p>
      </header>

      {configError && <div className="banner error" role="alert">Could not load the app configuration: {configError}</div>}

      {config && (
        <form className="card" onSubmit={submit} aria-label="Analysis settings">
          <div className="controls">
            <div>
              <div className="field">
                <span className="label">Region</span>
                <div className="selected-region" aria-live="polite">📍 <strong>{regionSummary(region)}</strong></div>
              </div>
              <RegionPicker region={region} maxBoxSpan={config.max_box_span_deg} onChange={setRegion} />
            </div>

            <div>
              <div className="field">
                <label htmlFor="hazard">Hazard type</label>
                <select id="hazard" value="heatwave" onChange={() => undefined}>
                  {config.hazards.map((h) => (
                    <option key={h.id} value={h.id} disabled={!h.available}>{h.label}{h.available ? '' : ' (coming soon)'}</option>
                  ))}
                </select>
              </div>

              <div className="field">
                <span className="label">Time range</span>
                <div className="row">
                  <div>
                    <label className="sr-only" htmlFor="y0">From year</label>
                    <select id="y0" value={startYear} onChange={(e) => setStartYear(Number(e.target.value))}>{yearOptions.map((y) => <option key={y} value={y}>{y}</option>)}</select>
                  </div>
                  <span style={{ flex: '0 0 auto', color: 'var(--text-3)' }}>to</span>
                  <div>
                    <label className="sr-only" htmlFor="y1">To year</label>
                    <select id="y1" value={endYear} onChange={(e) => setEndYear(Number(e.target.value))}>{yearOptions.map((y) => <option key={y} value={y}>{y}</option>)}</select>
                  </div>
                </div>
                <div className="chips" style={{ marginTop: 4 }}>
                  {[[1990, 2020], [1980, config.years.max], [2000, config.years.max], [config.years.min, config.years.max]].map(([a, b]) => (
                    <button key={`${a}-${b}`} type="button" className="chip" onClick={() => { setStartYear(a); setEndYear(b) }}>{a}–{b}</button>
                  ))}
                </div>
                {!yearsOk && <p role="alert" style={{ color: 'var(--bad)', fontSize: 13, margin: '4px 0 0' }}>Choose a range of at least {config.years.min_span} years (shorter windows can't reveal a climate trend).</p>}
              </div>

              <details className="adv">
                <summary>Heatwave definition (advanced)</summary>
                <div className="field">
                  <label htmlFor="pct">Percentile threshold</label>
                  <select id="pct" value={percentile} onChange={(e) => setPercentile(Number(e.target.value))}>{config.percentiles.map((p) => <option key={p} value={p}>{p}th percentile</option>)}</select>
                </div>
                <div className="field">
                  <label htmlFor="md">Minimum consecutive days</label>
                  <select id="md" value={minDays} onChange={(e) => setMinDays(Number(e.target.value))}>
                    {Array.from({ length: config.min_days.max - config.min_days.min + 1 }, (_, i) => config.min_days.min + i).map((d) => <option key={d} value={d}>{d}+ days</option>)}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="meth">Threshold method</label>
                  <select id="meth" value={method} onChange={(e) => setMethod(e.target.value as Method)}>{config.methods.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}</select>
                </div>
                <p className="legend-note">Thresholds always come from the {config.baseline.start_year}–{config.baseline.end_year} baseline, not from the range you select.</p>
              </details>

              <button className="btn primary" type="submit" disabled={!canRun} style={{ width: '100%', marginTop: 8 }}>
                {loading ? 'Analysing…' : 'Analyze heatwave trends'}
              </button>
            </div>
          </div>
        </form>
      )}

      <div style={{ marginTop: 16 }}>
        {error && (
          <div className="banner error" role="alert">
            {error}
            {retryIn !== null && <> Retrying automatically in {retryIn}s… <button type="button" className="chip" onClick={() => setRetryIn(null)}>Cancel</button></>}
          </div>
        )}
        {loading && !analysis && (
          <div className="stack" aria-busy="true">
            <div className="banner info">Fetching 75 years of daily temperatures for this location and analysing them. The first request for a new place takes a few seconds; after that it is served from the database instantly.</div>
            <div className="skeleton" style={{ height: 150 }} /><div className="skeleton" style={{ height: 340 }} />
          </div>
        )}
        {analysis && applied && (
          <div style={{ opacity: loading ? 0.55 : 1, transition: 'opacity .2s' }}>
            {loading && <div className="banner info" role="status">Updating…</div>}
            <Results analysis={analysis} query={applied} regionLabel={applied.region.label} year={year} yearDetail={yearDetail} yearLoading={yearLoading} yearError={yearError} onYear={setYear} />
          </div>
        )}
      </div>

      <footer>
        Data: <a href="https://open-meteo.com/" target="_blank" rel="noreferrer noopener">Open-Meteo</a> historical weather API (Copernicus ERA5 reanalysis), CC BY 4.0. Map tiles © OpenStreetMap contributors.
      </footer>
    </div>
  )
}
