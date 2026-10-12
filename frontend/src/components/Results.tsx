import { useMemo, useRef, useState } from 'react'
import type { Chart as ChartJS } from 'chart.js'
import { exportUrl } from '../api'
import { METRIC_LABEL, METRIC_ORDER, dateRange, num, pValue } from '../format'
import { exportPdf } from '../pdf'
import type { Analysis, HeatEvent, MetricKey, Query, YearDetail } from '../types'
import { EventsTimeline, TrendChart, YearExplorer } from './Charts'

interface Props {
  analysis: Analysis
  query: Query
  regionLabel: string
  year: number | null
  yearDetail: YearDetail | null
  yearLoading: boolean
  yearError: string | null
  onYear: (y: number) => void
}

function trendBadge(a: Analysis, k: MetricKey) {
  const mk = a.trends[k].mann_kendall
  if (!mk) return <span className="badge none">n/a</span>
  if (mk.trend === 'increasing') return <span className="badge up">▲ significant rise</span>
  if (mk.trend === 'decreasing') return <span className="badge down">▼ significant fall</span>
  return <span className="badge none">● no sig. trend</span>
}

function Tile({ a, k, active, onClick }: { a: Analysis; k: MetricKey; active: boolean; onClick: () => void }) {
  const t = a.trends[k]
  const pc = t.period_change
  const m = METRIC_LABEL[k]
  return (
    <button className="tile" aria-pressed={active} onClick={onClick}>
      <span className="k">{m.title}</span>
      <span className="v">{num(t.mean, 1)} <small>{m.unit}</small></span>
      <span className="d">
        {pc ? `${num(pc.early_mean, 1)} → ${num(pc.late_mean, 1)} (${pc.early_period[0]}–${String(pc.early_period[1]).slice(2)} → ${pc.late_period[0]}–${String(pc.late_period[1]).slice(2)})` : 'Not enough data'}
      </span>
      <span>{trendBadge(a, k)}</span>
    </button>
  )
}

type SortKey = 'start' | 'duration' | 'peak_c' | 'mean_excess_c' | 'heat_load'

function EventsTable({ events }: { events: HeatEvent[] }) {
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'duration', dir: -1 })
  const rows = useMemo(
    () => [...events].sort((a, b) => (a[sort.key] > b[sort.key] ? 1 : a[sort.key] < b[sort.key] ? -1 : 0) * sort.dir).slice(0, 100),
    [events, sort],
  )
  const head = (key: SortKey, label: string, num_ = true) => (
    <th className={num_ ? 'num' : ''} aria-sort={sort.key === key ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}>
      <button onClick={() => setSort((s) => ({ key, dir: s.key === key ? (s.dir === 1 ? -1 : 1) : -1 }))}>
        {label} {sort.key === key ? (sort.dir === 1 ? '▲' : '▼') : ''}
      </button>
    </th>
  )
  if (!events.length) return <p className="sub">No heatwave events were detected in this window.</p>
  return (
    <div className="table-scroll" tabIndex={0} aria-label="Heatwave events table">
      <table>
        <thead>
          <tr>
            {head('start', 'Dates', false)}
            {head('duration', 'Days')}
            {head('peak_c', 'Peak °C')}
            {head('mean_excess_c', 'Mean excess °C')}
            {head('heat_load', 'Heat load °C·d')}
          </tr>
        </thead>
        <tbody>
          {rows.map((e) => (
            <tr key={e.start}>
              <td>{dateRange(e)}</td>
              <td className="num">{e.duration}</td>
              <td className="num">{num(e.peak_c)}</td>
              <td className="num">+{num(e.mean_excess_c, 2)}</td>
              <td className="num">{num(e.heat_load)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Results({ analysis: a, query, regionLabel, year, yearDetail, yearLoading, yearError, onYear }: Props) {
  const [metric, setMetric] = useState<MetricKey>('days')
  const chartRef = useRef<ChartJS | null>(null)
  const [pdfBusy, setPdfBusy] = useState(false)
  const q = a.data_quality
  const years = a.plot.years

  const onPdf = async () => {
    setPdfBusy(true)
    try {
      await exportPdf(a, regionLabel, chartRef.current)
    } finally {
      setPdfBusy(false)
    }
  }

  return (
    <div className="stack" aria-live="polite">
      <section className="card">
        <div className="headline">
          <div className="icon" aria-hidden="true">🌡️</div>
          <div>
            <h2>{a.insights.headline}</h2>
            <p>
              {regionLabel} · {a.params.start_year}–{a.params.end_year} · {a.summary.total_events} heatwave events totalling {a.summary.total_heatwave_days} days
              {a.summary.longest_event && <> · longest: {a.summary.longest_event.duration} days ({dateRange(a.summary.longest_event)})</>}
            </p>
          </div>
        </div>
        <p className="def"><b>Definition:</b> {a.definition}. For reference, the {a.reference.period[0]}–{a.reference.period[1]} average is {num(a.reference.days)} heatwave days/yr.</p>
        {a.region.note && <p className="def">ⓘ {a.region.note}</p>}
        <div className="tiles">
          {METRIC_ORDER.map((k) => <Tile key={k} a={a} k={k} active={metric === k} onClick={() => setMetric(k)} />)}
        </div>
      </section>

      <section className="card">
        <h2>{METRIC_LABEL[metric].axis}</h2>
        <p className="sub">Bars are yearly values; click a bar to inspect that year below. Click legend items to show or hide the trend lines.</p>
        <TrendChart analysis={a} metric={metric} selectedYear={year} onSelectYear={onYear} chartRef={chartRef} />
        <details style={{ marginTop: 12 }}>
          <summary style={{ cursor: 'pointer', color: 'var(--text-2)', fontSize: 13 }}>View as table</summary>
          <div className="table-scroll" tabIndex={0} aria-label="Yearly values table" style={{ marginTop: 8 }}>
            <table>
              <thead><tr><th>Year</th>{METRIC_ORDER.map((k) => <th key={k} className="num">{METRIC_LABEL[k].title}</th>)}</tr></thead>
              <tbody>
                {years.map((y, i) => (
                  <tr key={y}>
                    <td>{y}{a.plot.valid[i] ? '' : ' (excluded)'}</td>
                    {METRIC_ORDER.map((k) => <td key={k} className="num">{num(a.plot.metrics[k][i], 2)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </section>

      <div className="grid2">
        <section className="card">
          <h2>Every heatwave event</h2>
          <p className="sub">Each dot is one event: higher = longer, bigger = hotter above the threshold.</p>
          <EventsTimeline analysis={a} />
          {a.events_truncated && <p className="legend-note">Showing the most recent {a.events.length} events.</p>}
        </section>
        <section className="card">
          <div className="row" style={{ alignItems: 'flex-end', marginBottom: 6 }}>
            <div>
              <h2>Year explorer</h2>
              <p className="sub" style={{ margin: 0 }}>Daily temperature vs. the heatwave threshold.</p>
            </div>
            <div style={{ flex: '0 0 130px' }}>
              <label className="sr-only" htmlFor="year-pick">Year to inspect</label>
              <select id="year-pick" value={year ?? ''} onChange={(e) => onYear(Number(e.target.value))}>
                {years.map((y) => <option key={y} value={y}>{y}</option>)}
              </select>
            </div>
          </div>
          {yearError ? <div className="banner error" role="alert">{yearError}</div>
            : yearDetail && !yearLoading ? <YearExplorer detail={yearDetail} />
            : <div className="skeleton chart-box short" />}
          {yearDetail && !yearLoading && (
            <p className="legend-note">{yearDetail.events.length ? `${yearDetail.events.length} heatwave${yearDetail.events.length > 1 ? 's' : ''} in ${yearDetail.year}: ${yearDetail.events.map((e) => `${e.start.slice(5)} (${e.duration}d)`).join(', ')}` : `No heatwave started in ${yearDetail.year}.`}</p>
          )}
        </section>
      </div>

      <section className="card">
        <h2>What the trends say</h2>
        <p className="sub">Mann-Kendall is the deciding test (robust for count data); OLS and Sen's slope give the size of the change.</p>
        {a.insights.items.map((i) => (
          <div className="insight-item" key={i.metric}>
            <span aria-hidden="true">{i.significant ? (i.direction === 'increase' ? '▲' : '▼') : '●'}</span>
            <span>{i.text}</span>
          </div>
        ))}
        <div className="table-scroll" tabIndex={0} aria-label="Trend statistics table" style={{ marginTop: 12 }}>
          <table>
            <thead>
              <tr><th>Metric</th><th className="num">Mean</th><th className="num">OLS slope /decade</th><th className="num">OLS p</th><th className="num">MK tau</th><th className="num">MK p</th><th className="num">Sen's slope /decade</th></tr>
            </thead>
            <tbody>
              {METRIC_ORDER.map((k) => {
                const t = a.trends[k]
                return (
                  <tr key={k}>
                    <td>{METRIC_LABEL[k].title}</td>
                    <td className="num">{num(t.mean, 2)}</td>
                    <td className="num">{num(t.linear_regression?.slope_per_decade, 2)}</td>
                    <td className="num">{pValue(t.linear_regression?.p_value)}</td>
                    <td className="num">{num(t.mann_kendall?.tau, 2)}</td>
                    <td className="num">{pValue(t.mann_kendall?.p_value)}</td>
                    <td className="num">{num(t.sens_slope_per_decade, 2)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <h3 style={{ fontSize: 14, margin: '16px 0 4px' }}>Read with care</h3>
        <ul className="clean">{a.insights.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
      </section>

      <section className="card">
        <h2>Events table</h2>
        <p className="sub">Sortable; up to 100 rows shown.</p>
        <EventsTable events={a.events} />
      </section>

      <section className="card">
        <h2>Data quality &amp; provenance</h2>
        <p className="sub">{a.meta.source}. Data through {a.meta.data_through_year}. Served from the {a.meta.store} database (analysis cache: {a.meta.cache.analysis}, raw data: {a.meta.cache.raw}).</p>
        <div className="qgrid">
          <div className="q"><b>{(q.valid_fraction * 100).toFixed(2)}%</b><span>valid days (1950–{a.meta.data_through_year})</span></div>
          <div className="q"><b>{q.missing_in_source}</b><span>missing in source</span></div>
          <div className="q"><b>{q.out_of_range_removed + q.spikes_removed}</b><span>implausible values removed (range &amp; spike checks)</span></div>
          <div className="q"><b>{q.gaps_interpolated_days}</b><span>days interpolated (gaps ≤ {q.rules.max_interpolated_gap_days} days)</span></div>
          <div className="q"><b>{a.summary.years_excluded.length}</b><span>years excluded (&lt; {Math.round(q.rules.min_year_coverage * 100)}% coverage)</span></div>
        </div>
        <p className="legend-note">Temperatures are daily maxima of 2 m air temperature in °C for the local calendar day, from the ERA5 grid cell at {a.region.grid_cell.lat}°, {a.region.grid_cell.lon}° (elevation {num(a.region.elevation_m, 0)} m).</p>
      </section>

      <section className="card">
        <h2>Export</h2>
        <div className="actions" style={{ marginTop: 8 }}>
          <a className="btn" href={exportUrl(query, 'annual')} download>⬇ Yearly stats (CSV)</a>
          <a className="btn" href={exportUrl(query, 'events')} download>⬇ Events (CSV)</a>
          <button className="btn" onClick={onPdf} disabled={pdfBusy}>{pdfBusy ? 'Building PDF…' : '⬇ Insight report (PDF)'}</button>
        </div>
      </section>
    </div>
  )
}
