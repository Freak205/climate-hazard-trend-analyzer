import type { HeatEvent, MetricKey } from './types'

export const METRIC_ORDER: MetricKey[] = ['days', 'frequency', 'mean_duration', 'intensity']

export const METRIC_LABEL: Record<MetricKey, { title: string; axis: string; unit: string }> = {
  days: { title: 'Heatwave days', axis: 'Heatwave days per year', unit: 'days/yr' },
  frequency: { title: 'Frequency', axis: 'Heatwave events per year', unit: 'events/yr' },
  mean_duration: { title: 'Avg. duration', axis: 'Days per event', unit: 'days' },
  intensity: { title: 'Intensity', axis: '°C above threshold (mean per heatwave day)', unit: '°C' },
}

export function num(x: number | null | undefined, digits = 1): string {
  if (x === null || x === undefined || Number.isNaN(x)) return '–'
  return x.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits === 0 ? 0 : 0 })
}

export function pValue(p: number | null | undefined): string {
  if (p === null || p === undefined) return '–'
  return p < 0.001 ? '< 0.001' : p.toFixed(3)
}

export function dateRange(e: HeatEvent): string {
  const f = (s: string) => new Date(s + 'T00:00:00Z').toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
  return e.start === e.end ? f(e.start) : `${f(e.start)} – ${f(e.end)}`
}

/** Decimal year for plotting events on a numeric time axis. */
export function decimalYear(iso: string): number {
  const d = new Date(iso + 'T00:00:00Z')
  const start = Date.UTC(d.getUTCFullYear(), 0, 1)
  const end = Date.UTC(d.getUTCFullYear() + 1, 0, 1)
  return d.getUTCFullYear() + (d.getTime() - start) / (end - start)
}
