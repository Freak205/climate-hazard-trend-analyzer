import { Suspense, lazy, useEffect, useMemo, useState } from 'react'
import { searchPlaces } from '../api'
import { ALL_PRESETS, CITY_PRESETS, STATE_PRESETS, placeLabel } from '../places'
import type { Place, Region } from '../types'
import type { MapMode } from './MapPicker'

const MapPicker = lazy(() => import('./MapPicker'))

interface Props {
  region: Region
  maxBoxSpan: number
  onChange: (r: Region) => void
}

const fmt = (x: number) => x.toFixed(2)
export function regionSummary(r: Region): string {
  return r.kind === 'point'
    ? `${r.label} (${fmt(r.lat)}°, ${fmt(r.lon)}°)`
    : `${r.label} (${fmt(r.minLat)}–${fmt(r.maxLat)}°N, ${fmt(r.minLon)}–${fmt(r.maxLon)}°E)`
}

export function RegionPicker({ region, maxBoxSpan, onChange }: Props) {
  const [tab, setTab] = useState<'search' | 'map'>('search')
  const [mode, setMode] = useState<MapMode>('point')
  const [text, setText] = useState('')
  const [remote, setRemote] = useState<Place[]>([])
  const [status, setStatus] = useState<'idle' | 'loading' | 'error'>('idle')
  const [message, setMessage] = useState('')

  const trimmed = text.trim()
  const local = useMemo(
    () => (trimmed.length < 2 ? [] : ALL_PRESETS.filter((p) => p.name.toLowerCase().includes(trimmed.toLowerCase())).slice(0, 6)),
    [trimmed],
  )

  // Debounced geocoding with request cancellation.
  useEffect(() => {
    if (trimmed.length < 2 || !/^[\p{L}\p{N}\s.,'()’-]+$/u.test(trimmed)) {
      setRemote([])
      setStatus('idle')
      return
    }
    const ctl = new AbortController()
    const t = setTimeout(() => {
      setStatus('loading')
      searchPlaces(trimmed, ctl.signal)
        .then((r) => {
          setRemote(r)
          setStatus('idle')
          setMessage(r.length ? '' : 'No cities found. Try a nearby city, or use the map.')
        })
        .catch((e: Error) => {
          if (e.name === 'AbortError') return
          setStatus('error')
          setMessage(e.message)
        })
    }, 380)
    return () => {
      clearTimeout(t)
      ctl.abort()
    }
  }, [trimmed])

  const pick = (p: Place) => {
    onChange({ kind: 'point', lat: p.lat, lon: p.lon, label: placeLabel(p) })
    setText('')
    setRemote([])
  }

  const seen = new Set(local.map((p) => `${p.lat},${p.lon}`))
  const results = [...local, ...remote.filter((p) => !seen.has(`${p.lat},${p.lon}`))]

  const box = region.kind === 'box' ? region : null
  const setBoxField = (key: 'minLat' | 'maxLat' | 'minLon' | 'maxLon', v: string) => {
    if (!box) return
    const n = Number(v)
    if (v === '' || Number.isNaN(n)) return
    onChange({ ...box, [key]: n, label: 'Custom box' })
  }
  const boxError =
    box &&
    (box.minLat >= box.maxLat || box.minLon >= box.maxLon
      ? 'Minimums must be smaller than maximums.'
      : box.maxLat - box.minLat > maxBoxSpan || box.maxLon - box.minLon > maxBoxSpan
        ? `Each side may span at most ${maxBoxSpan}°.`
        : box.minLat < -90 || box.maxLat > 90 || box.minLon < -180 || box.maxLon > 180
          ? 'Coordinates are out of range.'
          : null)

  return (
    <div>
      <div className="tabs" role="tablist" aria-label="How to choose a region">
        <button role="tab" aria-selected={tab === 'search'} onClick={() => setTab('search')}>City / state</button>
        <button role="tab" aria-selected={tab === 'map'} onClick={() => setTab('map')}>Map &amp; custom box</button>
      </div>

      {tab === 'search' ? (
        <div>
          <label className="sr-only" htmlFor="place-search">Search for a city</label>
          <input id="place-search" type="text" inputMode="search" autoComplete="off" maxLength={60} placeholder="Search a city, e.g. Jaipur, Phoenix, Madrid…" value={text} onChange={(e) => setText(e.target.value)} />
          {(results.length > 0 || status !== 'idle' || message) && trimmed.length >= 2 && (
            <ul className="results-list" aria-label="Search results">
              {results.map((p) => (
                <li key={`${p.lat},${p.lon},${p.name}`}>
                  <button type="button" onClick={() => pick(p)}>
                    {p.name} <small>{[p.admin1, p.country].filter(Boolean).join(', ')}</small>
                  </button>
                </li>
              ))}
              {status === 'loading' && <li style={{ padding: '9px 12px', color: 'var(--text-3)' }}>Searching…</li>}
              {status !== 'loading' && results.length === 0 && message && (
                <li style={{ padding: '9px 12px', color: status === 'error' ? 'var(--bad)' : 'var(--text-3)' }}>{message}</li>
              )}
            </ul>
          )}
          <p className="sub" style={{ margin: '12px 0 6px' }}>Cities</p>
          <div className="chips">{CITY_PRESETS.map((p) => <button key={p.name} className="chip" type="button" onClick={() => pick(p)}>{p.name}</button>)}</div>
          <p className="sub" style={{ margin: '12px 0 6px' }}>States &amp; regions (analysed at their centre point)</p>
          <div className="chips">{STATE_PRESETS.map((p) => <button key={p.name} className="chip" type="button" onClick={() => pick(p)}>{p.name}</button>)}</div>
        </div>
      ) : (
        <div>
          <div className="tabs" role="tablist" aria-label="Map tool">
            <button role="tab" aria-selected={mode === 'point'} onClick={() => setMode('point')}>Pick a point</button>
            <button role="tab" aria-selected={mode === 'box'} onClick={() => setMode('box')}>Draw a box</button>
          </div>
          <p className="sub" style={{ margin: '0 0 8px' }}>
            {mode === 'point' ? 'Click anywhere on the map.' : 'Click and drag to draw a rectangle (max ' + maxBoxSpan + '° per side).'}
          </p>
          <Suspense fallback={<div className="skeleton" style={{ height: 300 }} />}>
            <MapPicker
              region={region}
              mode={mode}
              onPoint={(lat, lon) => onChange({ kind: 'point', lat, lon, label: 'Map point' })}
              onBox={(minLat, minLon, maxLat, maxLon) => onChange({ kind: 'box', minLat, minLon, maxLat, maxLon, label: 'Custom box' })}
            />
          </Suspense>
          {region.kind === 'point' ? (
            <div className="box-grid" style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}>
              <label>Latitude<input type="number" step="0.01" min={-90} max={90} value={region.lat} onChange={(e) => e.target.value !== '' && onChange({ ...region, lat: Number(e.target.value), label: 'Map point' })} /></label>
              <label>Longitude<input type="number" step="0.01" min={-180} max={180} value={region.lon} onChange={(e) => e.target.value !== '' && onChange({ ...region, lon: Number(e.target.value), label: 'Map point' })} /></label>
            </div>
          ) : (
            <>
              <div className="box-grid">
                <label>Min lat<input type="number" step="0.01" value={box!.minLat} onChange={(e) => setBoxField('minLat', e.target.value)} /></label>
                <label>Max lat<input type="number" step="0.01" value={box!.maxLat} onChange={(e) => setBoxField('maxLat', e.target.value)} /></label>
                <label>Min lon<input type="number" step="0.01" value={box!.minLon} onChange={(e) => setBoxField('minLon', e.target.value)} /></label>
                <label>Max lon<input type="number" step="0.01" value={box!.maxLon} onChange={(e) => setBoxField('maxLon', e.target.value)} /></label>
              </div>
              {boxError && <p role="alert" style={{ color: 'var(--bad)', margin: '8px 0 0', fontSize: 13 }}>{boxError}</p>}
              <p className="legend-note">A box is analysed at the ERA5 grid cell at its centre.</p>
            </>
          )}
        </div>
      )}
    </div>
  )
}

export function boxIsValid(r: Region, maxSpan: number): boolean {
  if (r.kind === 'point') return r.lat >= -90 && r.lat <= 90 && r.lon >= -180 && r.lon <= 180
  return r.minLat < r.maxLat && r.minLon < r.maxLon && r.maxLat - r.minLat <= maxSpan && r.maxLon - r.minLon <= maxSpan &&
    r.minLat >= -90 && r.maxLat <= 90 && r.minLon >= -180 && r.maxLon <= 180
}
