import { useEffect, useState } from 'react'
import {
  BarController, BarElement, CategoryScale, Chart, Filler, Legend, LinearScale, LineController,
  LineElement, PointElement, ScatterController, Tooltip,
} from 'chart.js'

Chart.register(
  BarController, BarElement, CategoryScale, Filler, Legend, LinearScale, LineController,
  LineElement, PointElement, ScatterController, Tooltip,
)

export interface ChartColors {
  text: string
  text2: string
  grid: string
  surface: string
  s1: string
  s2: string
  s3: string
  s8: string
}

function read(): ChartColors {
  const cs = getComputedStyle(document.documentElement)
  const v = (n: string) => cs.getPropertyValue(n).trim()
  return { text: v('--text'), text2: v('--text-2'), grid: v('--grid'), surface: v('--surface'), s1: v('--s1'), s2: v('--s2'), s3: v('--s3'), s8: v('--s8') }
}

/** Chart.js draws on canvas, so it needs concrete colours: re-read them when the OS theme flips. */
export function useChartColors(): ChartColors {
  const [colors, setColors] = useState<ChartColors>(read)
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const on = () => setColors(read())
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return colors
}

export function baseOptions(c: ChartColors) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 250 },
    interaction: { mode: 'index' as const, intersect: false },
    plugins: {
      legend: { position: 'bottom' as const, labels: { color: c.text2, usePointStyle: true, boxWidth: 8, boxHeight: 8, padding: 14 } },
      tooltip: { backgroundColor: c.surface, titleColor: c.text, bodyColor: c.text2, borderColor: c.grid, borderWidth: 1, padding: 10, boxPadding: 4 },
    },
  }
}
