import { useMemo, type RefObject } from 'react'
import { Chart as ReactChart } from 'react-chartjs-2'
import type { Chart as ChartJS } from 'chart.js'
import { baseOptions, useChartColors } from '../chartSetup'
import { METRIC_LABEL, decimalYear, num } from '../format'
import type { Analysis, HeatEvent, MetricKey, YearDetail } from '../types'

const hexA = (hex: string, a: number) => {
  const h = hex.replace('#', '')
  if (h.length !== 6) return hex
  const n = parseInt(h, 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`
}

/* ------------------------------------------------------------------ trend */
interface TrendProps {
  analysis: Analysis
  metric: MetricKey
  selectedYear: number | null
  onSelectYear: (y: number) => void
  chartRef: RefObject<ChartJS | null>
}

export function TrendChart({ analysis, metric, selectedYear, onSelectYear, chartRef }: TrendProps) {
  const c = useChartColors()
  const { years, metrics, valid } = analysis.plot
  const trend = analysis.trends[metric]
  const label = METRIC_LABEL[metric]

  const data = useMemo(
    () => ({
      labels: years,
      datasets: [
        {
          type: 'bar' as const,
          label: label.title,
          data: metrics[metric],
          backgroundColor: years.map((y) => (y === selectedYear ? c.s1 : hexA(c.s1, 0.62))),
          borderRadius: { topLeft: 4, topRight: 4 },
          borderSkipped: 'bottom' as const,
          maxBarThickness: 22,
          order: 3,
        },
        {
          type: 'line' as const,
          label: '5-year rolling mean',
          data: trend.series.rolling_mean_5y,
          borderColor: c.s2,
          backgroundColor: c.s2,
          borderWidth: 2.5,
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0.25,
          spanGaps: true,
          order: 1,
        },
        {
          type: 'line' as const,
          label: 'Linear trend (OLS)',
          data: trend.series.regression_line,
          borderColor: c.s3,
          backgroundColor: c.s3,
          borderWidth: 2,
          borderDash: [7, 5],
          pointRadius: 0,
          pointHoverRadius: 3,
          order: 2,
        },
        {
          type: 'line' as const,
          label: "Theil–Sen trend",
          data: trend.series.sen_line,
          borderColor: c.text2,
          backgroundColor: c.text2,
          borderWidth: 2,
          borderDash: [2, 4],
          pointRadius: 0,
          hidden: true,
          order: 2,
        },
      ],
    }),
    [years, metrics, metric, trend, label.title, selectedYear, c],
  )

  const options = useMemo(() => {
    const base = baseOptions(c)
    return {
      ...base,
      onClick: (_: unknown, __: unknown, chart: ChartJS) => {
        const act = chart.getActiveElements()
        if (act.length) onSelectYear(years[act[0].index])
      },
      onHover: (e: { native: Event | null }, els: unknown[]) => {
        const t = e.native?.target as HTMLElement | undefined
        if (t) t.style.cursor = els.length ? 'pointer' : 'default'
      },
      plugins: {
        ...base.plugins,
        tooltip: {
          ...base.plugins.tooltip,
          callbacks: {
            title: (items: { label: string }[]) => (items.length ? `${items[0].label}${valid[years.indexOf(Number(items[0].label))] === false ? ' (excluded: poor data coverage)' : ''}` : ''),
            label: (ctx: { dataset: { label?: string }; parsed: { y: number | null } }) =>
              `${ctx.dataset.label}: ${ctx.parsed.y === null ? 'n/a' : num(ctx.parsed.y, 2)}`,
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: c.text2, maxRotation: 0, autoSkipPadding: 12 }, border: { color: c.grid } },
        y: {
          beginAtZero: true,
          grid: { color: c.grid },
          border: { display: false },
          ticks: { color: c.text2 },
          title: { display: true, text: label.axis, color: c.text2 },
        },
      },
    }
  }, [c, label.axis, onSelectYear, years, valid])

  const summary = `${label.title} per year, ${years[0]} to ${years[years.length - 1]}, with 5-year rolling mean and linear trend.`
  return (
    <div className="chart-box" role="img" aria-label={summary}>
      {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
      <ReactChart ref={chartRef as any} type="bar" data={data as any} options={options as any} />
    </div>
  )
}

/* --------------------------------------------------------------- timeline */
export function EventsTimeline({ analysis }: { analysis: Analysis }) {
  const c = useChartColors()
  const { start_year, end_year } = analysis.params
  const events = analysis.events

  const data = useMemo(
    () => ({
      datasets: [
        {
          type: 'scatter' as const,
          label: 'Heatwave event',
          data: events.map((e) => ({ x: decimalYear(e.start), y: e.duration, e })),
          backgroundColor: hexA(c.s2, 0.6),
          borderColor: c.surface,
          borderWidth: 1.5,
          pointRadius: events.map((e) => Math.max(3.5, Math.min(13, 3 + e.mean_excess_c * 3.2))),
          pointHoverRadius: events.map((e) => Math.max(5, Math.min(15, 5 + e.mean_excess_c * 3.2))),
        },
      ],
    }),
    [events, c],
  )

  const options = useMemo(() => {
    const base = baseOptions(c)
    return {
      ...base,
      interaction: { mode: 'nearest' as const, intersect: true },
      plugins: {
        ...base.plugins,
        legend: { display: false },
        tooltip: {
          ...base.plugins.tooltip,
          callbacks: {
            title: (items: { raw: { e: HeatEvent } }[]) => (items[0] ? `${items[0].raw.e.start} → ${items[0].raw.e.end}` : ''),
            label: (ctx: { raw: { e: HeatEvent } }) => {
              const e = ctx.raw.e
              return [`Duration: ${e.duration} days`, `Peak: ${num(e.peak_c)} °C`, `Mean exceedance: +${num(e.mean_excess_c, 2)} °C`, `Heat load: ${num(e.heat_load)} °C·days`]
            },
          },
        },
      },
      scales: {
        x: {
          min: start_year,
          max: end_year + 1,
          grid: { color: c.grid },
          border: { display: false },
          ticks: { color: c.text2, callback: (v: string | number) => (Number.isInteger(Number(v)) ? String(v) : ''), maxRotation: 0, autoSkipPadding: 14 },
        },
        y: {
          beginAtZero: true,
          grid: { color: c.grid },
          border: { display: false },
          ticks: { color: c.text2, precision: 0 },
          title: { display: true, text: 'Duration (days)', color: c.text2 },
        },
      },
    }
  }, [c, start_year, end_year])

  return (
    <div className="chart-box short" role="img" aria-label={`Each heatwave event from ${start_year} to ${end_year}: x is time, y is duration in days, dot size is intensity.`}>
      {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
      <ReactChart type="scatter" data={data as any} options={options as any} />
    </div>
  )
}

/* ---------------------------------------------------------- year explorer */
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function YearExplorer({ detail }: { detail: YearDetail }) {
  const c = useChartColors()
  const data = useMemo(
    () => ({
      labels: detail.dates,
      datasets: [
        { type: 'line' as const, label: 'Daily max temperature', data: detail.tmax, borderColor: c.s1, backgroundColor: c.s1, borderWidth: 1.6, pointRadius: 0, pointHoverRadius: 3, spanGaps: false, order: 3 },
        { type: 'line' as const, label: 'Heatwave threshold', data: detail.threshold, borderColor: c.s2, backgroundColor: c.s2, borderWidth: 2, borderDash: [6, 4], pointRadius: 0, order: 2 },
        {
          type: 'line' as const,
          label: 'Heatwave day',
          data: detail.tmax.map((v, i) => (detail.in_heatwave[i] ? v : null)),
          showLine: false,
          borderColor: c.surface,
          backgroundColor: c.s8,
          borderWidth: 1,
          pointRadius: 4.5,
          pointHoverRadius: 6,
          order: 1,
        },
      ],
    }),
    [detail, c],
  )

  const options = useMemo(() => {
    const base = baseOptions(c)
    return {
      ...base,
      plugins: {
        ...base.plugins,
        tooltip: {
          ...base.plugins.tooltip,
          callbacks: {
            title: (items: { label: string }[]) => items[0]?.label ?? '',
            label: (ctx: { dataset: { label?: string }; parsed: { y: number | null } }) => `${ctx.dataset.label}: ${num(ctx.parsed.y)} °C`,
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          border: { color: c.grid },
          ticks: {
            color: c.text2,
            autoSkip: false,
            maxRotation: 0,
            callback: (_: unknown, i: number) => (detail.dates[i]?.endsWith('-01') ? MONTHS[Number(detail.dates[i].slice(5, 7)) - 1] : ''),
          },
        },
        y: { grid: { color: c.grid }, border: { display: false }, ticks: { color: c.text2 }, title: { display: true, text: 'Temperature (°C)', color: c.text2 } },
      },
    }
  }, [c, detail])

  return (
    <div className="chart-box short" role="img" aria-label={`Daily maximum temperature in ${detail.year} against the heatwave threshold; heatwave days highlighted.`}>
      {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
      <ReactChart type="line" data={data as any} options={options as any} />
    </div>
  )
}
