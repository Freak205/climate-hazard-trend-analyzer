import type { AppConfig, Analysis, Place, Query, YearDetail } from './types'

export class ApiClientError extends Error {
  constructor(message: string, public status: number, public retryAfter?: number, public code?: string) {
    super(message)
  }
}

async function getJson<T>(path: string, params: URLSearchParams | null, signal?: AbortSignal): Promise<T> {
  const url = params ? `${path}?${params.toString()}` : path
  let res: Response
  try {
    res = await fetch(url, { signal, headers: { Accept: 'application/json' } })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiClientError('Could not reach the server. Check your connection and try again.', 0)
  }
  if (!res.ok) {
    let message = `Request failed (${res.status}).`
    let code: string | undefined
    try {
      const body = await res.json()
      if (body?.error?.message) message = body.error.message
      code = body?.error?.code
    } catch {
      /* non-JSON error body (e.g. gateway timeout) */
      if (res.status === 504) message = 'The server took too long to respond. Please try again.'
    }
    throw new ApiClientError(message, res.status, Number(res.headers.get('Retry-After')) || undefined, code)
  }
  return (await res.json()) as T
}

/** Serialise the region part of a query (point or box) as API parameters. */
export function regionParams(q: Query['region']): URLSearchParams {
  const p = new URLSearchParams()
  if (q.kind === 'point') {
    p.set('lat', q.lat.toFixed(4))
    p.set('lon', q.lon.toFixed(4))
  } else {
    p.set('min_lat', q.minLat.toFixed(4))
    p.set('min_lon', q.minLon.toFixed(4))
    p.set('max_lat', q.maxLat.toFixed(4))
    p.set('max_lon', q.maxLon.toFixed(4))
  }
  return p
}

export function hazardParams(q: Query): URLSearchParams {
  const p = regionParams(q.region)
  p.set('hazard', 'heatwave')
  p.set('percentile', String(q.percentile))
  p.set('min_days', String(q.minDays))
  p.set('method', q.method)
  return p
}

export function analysisParams(q: Query): URLSearchParams {
  const p = hazardParams(q)
  p.set('start_year', String(q.startYear))
  p.set('end_year', String(q.endYear))
  return p
}

export const fetchConfig = (signal?: AbortSignal) => getJson<AppConfig>('/api/config', null, signal)

export const fetchAnalysis = (q: Query, signal?: AbortSignal) =>
  getJson<Analysis>('/api/analysis', analysisParams(q), signal)

export function fetchYear(q: Query, year: number, signal?: AbortSignal) {
  const p = hazardParams(q)
  p.set('year', String(year))
  return getJson<YearDetail>('/api/year', p, signal)
}

export async function searchPlaces(text: string, signal?: AbortSignal): Promise<Place[]> {
  const body = await getJson<{ results: Place[] }>('/api/geocode', new URLSearchParams({ q: text }), signal)
  return body.results
}

export function exportUrl(q: Query, dataset: 'annual' | 'events'): string {
  const p = analysisParams(q)
  p.set('dataset', dataset)
  return `/api/export?${p.toString()}`
}
