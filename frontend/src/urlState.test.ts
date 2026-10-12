import { describe, expect, it } from 'vitest'
import { parseQuery, queryToSearch } from './urlState'
import { latin1 } from './pdf'
import type { AppConfig, Query } from './types'

const cfg: AppConfig = {
  hazards: [],
  percentiles: [90, 92.5, 95, 97.5, 99],
  methods: [],
  min_days: { min: 2, max: 7, default: 3 },
  years: { min: 1950, max: 2025, min_span: 10, default_start: 1990, default_end: 2020 },
  baseline: { start_year: 1991, end_year: 2020 },
  max_box_span_deg: 30,
}

const q: Query = { region: { kind: 'point', lat: 28.61, lon: 77.21, label: 'Delhi, India' }, startYear: 1990, endYear: 2020, percentile: 95, minDays: 3, method: 'calendar_day' }

describe('shareable URL state', () => {
  it('round-trips a point query', () => {
    expect(parseQuery(queryToSearch(q), cfg)).toEqual(q)
  })

  it('round-trips a box query', () => {
    const box: Query = { ...q, region: { kind: 'box', minLat: 20, minLon: 70, maxLat: 30, maxLon: 80, label: 'Custom box' } }
    expect(parseQuery(queryToSearch(box), cfg)).toEqual(box)
  })

  it('rejects out-of-range or malformed input instead of trusting it', () => {
    expect(parseQuery('?lat=95&lon=10', cfg)).toBeNull()
    expect(parseQuery('?lat=abc&lon=10', cfg)).toBeNull()
    expect(parseQuery('?minLat=0&maxLat=60&minLon=0&maxLon=10', cfg)).toBeNull() // 60 deg > max span
    expect(parseQuery('?lat=10&lon=10&from=2015&to=2020', cfg)).toBeNull() // < min span
    expect(parseQuery('', cfg)).toBeNull()
  })

  it('clamps years and falls back on unknown enum values', () => {
    const r = parseQuery('?lat=10&lon=10&from=1800&to=2999&pct=13&days=99&method=evil', cfg)!
    expect(r.startYear).toBe(1950)
    expect(r.endYear).toBe(2025)
    expect(r.percentile).toBe(95)
    expect(r.minDays).toBe(7)
    expect(r.method).toBe('calendar_day')
  })

  it('strips markup characters from the shared place name', () => {
    const r = parseQuery('?lat=10&lon=10&name=%3Cimg%20src%3Dx%20onerror%3Dalert(1)%3E', cfg)!
    expect(r.region.label).not.toMatch(/[<>=]/)
  })
})

describe('pdf text sanitiser', () => {
  it('maps non-Latin-1 symbols so jsPDF renders them', () => {
    expect(latin1('1.6 → 1.1, 1990–2020 …')).toBe('1.6 -> 1.1, 1990-2020 ...')
  })
})
