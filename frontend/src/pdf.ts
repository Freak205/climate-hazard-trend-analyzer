import type { Chart } from 'chart.js'
import { METRIC_LABEL, METRIC_ORDER, dateRange, num, pValue } from './format'
import type { Analysis } from './types'

/** jsPDF's built-in fonts are Latin-1 only: map the few other symbols we use. */
export function latin1(s: string): string {
  return s
    .replace(/[→➔]/g, '->')
    .replace(/[–—]/g, '-')
    .replace(/[‘’]/g, "'")
    .replace(/[“”]/g, '"')
    .replace(/…/g, '...')
    .replace(/[^\x00-\xff]/g, '?')
}

function chartPng(chart: Chart | null): string | null {
  if (!chart) return null
  const src = chart.canvas
  const out = document.createElement('canvas')
  out.width = src.width
  out.height = src.height
  const ctx = out.getContext('2d')
  if (!ctx) return null
  ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--surface').trim() || '#ffffff'
  ctx.fillRect(0, 0, out.width, out.height)
  ctx.drawImage(src, 0, 0)
  return out.toDataURL('image/png')
}

export async function exportPdf(a: Analysis, regionLabel: string, chart: Chart | null): Promise<void> {
  const { jsPDF } = await import('jspdf') // loaded on demand: keeps the initial bundle small
  const doc = new jsPDF({ unit: 'pt', format: 'a4' })
  const W = doc.internal.pageSize.getWidth()
  const M = 44
  let y = M

  const write = (text: string, size = 10, bold = false, gap = 6, color: [number, number, number] = [30, 30, 30]) => {
    doc.setFont('helvetica', bold ? 'bold' : 'normal').setFontSize(size).setTextColor(...color)
    for (const line of doc.splitTextToSize(latin1(text), W - 2 * M) as string[]) {
      if (y > 790) { doc.addPage(); y = M }
      doc.text(line, M, y)
      y += size * 1.3
    }
    y += gap
  }

  write('Heatwave trend report', 20, true, 2)
  write(`${regionLabel}  |  ${a.params.start_year}-${a.params.end_year}`, 11, false, 10, [90, 90, 90])
  write(a.insights.headline, 13, true, 8)
  write(`Definition: ${a.definition}.`, 9.5, false, 4, [80, 80, 80])
  write(`ERA5 grid cell used: ${a.region.grid_cell.lat}, ${a.region.grid_cell.lon}. Reference (${a.reference.period[0]}-${a.reference.period[1]}) average: ${num(a.reference.days)} heatwave days/yr.`, 9.5, false, 10, [80, 80, 80])

  const png = chartPng(chart)
  if (png) {
    const w = W - 2 * M
    const h = w * (chart!.canvas.height / chart!.canvas.width)
    if (y + h > 790) { doc.addPage(); y = M }
    doc.addImage(png, 'PNG', M, y, w, h)
    y += h + 12
  }

  write('Trend statistics', 12, true, 4)
  for (const k of METRIC_ORDER) {
    const t = a.trends[k]
    const mk = t.mann_kendall
    write(
      `${METRIC_LABEL[k].title}: mean ${num(t.mean, 2)} ${METRIC_LABEL[k].unit}; OLS slope ${num(t.linear_regression?.slope_per_decade, 2)}/decade (p ${pValue(t.linear_regression?.p_value)}); ` +
        `Mann-Kendall tau ${num(mk?.tau, 2)} (p ${pValue(mk?.p_value)}); Sen's slope ${num(t.sens_slope_per_decade, 2)}/decade.`,
      9.5, false, 3,
    )
  }
  y += 6
  write('Insights', 12, true, 4)
  for (const i of a.insights.items) write(`- ${i.text}`, 9.5, false, 3)
  y += 6
  write('Longest events', 12, true, 4)
  for (const e of [...a.events].sort((x, z) => z.duration - x.duration).slice(0, 10)) {
    write(`${dateRange(e)}: ${e.duration} days, peak ${num(e.peak_c)} C, +${num(e.mean_excess_c, 2)} C mean exceedance`, 9.5, false, 2)
  }
  y += 8
  write('Caveats', 12, true, 4)
  for (const c of a.insights.caveats) write(`- ${c}`, 9, false, 2, [80, 80, 80])
  write(`Source: ${a.meta.source}. Generated ${new Date().toISOString().slice(0, 10)}.`, 8.5, false, 0, [120, 120, 120])

  doc.save(`heatwave-report-${a.region.grid_cell.lat}_${a.region.grid_cell.lon}_${a.params.start_year}-${a.params.end_year}.pdf`)
}
