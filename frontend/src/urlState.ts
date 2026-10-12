import type { AppConfig, Method, Query, Region } from './types'

const num = (v: string | null): number | null => {
  if (v === null || v.trim() === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}
const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n))

/** Serialise an applied query so the current view can be shared as a link. */
export function queryToSearch(q: Query): string {
  const p = new URLSearchParams()
  const r = q.region
  if (r.kind === 'point') {
    p.set('lat', r.lat.toFixed(2)); p.set('lon', r.lon.toFixed(2))
  } else {
    p.set('minLat', String(r.minLat)); p.set('minLon', String(r.minLon)); p.set('maxLat', String(r.maxLat)); p.set('maxLon', String(r.maxLon))
  }
  p.set('name', r.label.slice(0, 80))
  p.set('from', String(q.startYear)); p.set('to', String(q.endYear))
  p.set('pct', String(q.percentile)); p.set('days', String(q.minDays)); p.set('method', q.method)
  return `?${p.toString()}`
}

/** Parse + sanitise a shared link. Anything unexpected falls back to defaults (null). */
export function parseQuery(search: string, cfg: AppConfig): Query | null {
  const p = new URLSearchParams(search)
  const label = (p.get('name') ?? '').replace(/[^\p{L}\p{N}\s.,'()’-]/gu, '').slice(0, 80)
  let region: Region | null = null
  const lat = num(p.get('lat')), lon = num(p.get('lon'))
  if (lat !== null && lon !== null && Math.abs(lat) <= 90 && Math.abs(lon) <= 180) {
    region = { kind: 'point', lat, lon, label: label || 'Map point' }
  } else {
    const b = ['minLat', 'minLon', 'maxLat', 'maxLon'].map((k) => num(p.get(k)))
    if (b.every((x) => x !== null)) {
      const [minLat, minLon, maxLat, maxLon] = b as number[]
      if (minLat < maxLat && minLon < maxLon && minLat >= -90 && maxLat <= 90 && minLon >= -180 && maxLon <= 180 &&
        maxLat - minLat <= cfg.max_box_span_deg && maxLon - minLon <= cfg.max_box_span_deg) {
        region = { kind: 'box', minLat, minLon, maxLat, maxLon, label: label || 'Custom box' }
      }
    }
  }
  if (!region) return null
  const from = clamp(Math.round(num(p.get('from')) ?? cfg.years.default_start), cfg.years.min, cfg.years.max)
  const to = clamp(Math.round(num(p.get('to')) ?? cfg.years.default_end), cfg.years.min, cfg.years.max)
  const pct = cfg.percentiles.includes(num(p.get('pct')) ?? -1) ? (num(p.get('pct')) as number) : 95
  const days = clamp(Math.round(num(p.get('days')) ?? cfg.min_days.default), cfg.min_days.min, cfg.min_days.max)
  const method: Method = p.get('method') === 'fixed' ? 'fixed' : 'calendar_day'
  if (to - from + 1 < cfg.years.min_span) return null
  return { region, startYear: from, endYear: to, percentile: pct, minDays: days, method }
}
