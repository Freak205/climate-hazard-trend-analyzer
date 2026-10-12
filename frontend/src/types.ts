export type MetricKey = 'frequency' | 'days' | 'mean_duration' | 'intensity'
export type Method = 'calendar_day' | 'fixed'

export interface AppConfig {
  hazards: { id: string; label: string; available: boolean; default: boolean; description: string }[]
  percentiles: number[]
  methods: { id: Method; label: string }[]
  min_days: { min: number; max: number; default: number }
  years: { min: number; max: number; min_span: number; default_start: number; default_end: number }
  baseline: { start_year: number; end_year: number }
  max_box_span_deg: number
}

export type Region =
  | { kind: 'point'; lat: number; lon: number; label: string }
  | { kind: 'box'; minLat: number; minLon: number; maxLat: number; maxLon: number; label: string }

export interface Query {
  region: Region
  startYear: number
  endYear: number
  percentile: number
  minDays: number
  method: Method
}

export interface HeatEvent {
  start: string
  end: string
  year: number
  duration: number
  peak_c: number
  mean_c: number
  mean_excess_c: number
  max_excess_c: number
  heat_load: number
}

export interface TrendBlock {
  n_years: number
  mean: number | null
  linear_regression: { slope_per_decade: number; p_value: number; r2: number; stderr_per_decade: number } | null
  mann_kendall: { tau: number; z: number; p_value: number; trend: 'increasing' | 'decreasing' | 'none' } | null
  sens_slope_per_decade: number | null
  period_change: {
    early_period: [number, number]
    late_period: [number, number]
    early_mean: number
    late_mean: number
    abs_change: number
    pct_change: number | null
  } | null
  series: {
    rolling_mean_5y: (number | null)[]
    regression_line: (number | null)[]
    sen_line: (number | null)[]
  }
}

export interface Insight {
  metric: MetricKey
  direction: 'increase' | 'decrease' | 'none' | 'flat' | 'insufficient'
  significant: boolean
  pct_change?: number | null
  text: string
}

export interface Analysis {
  hazard: string
  region: {
    kind: 'point' | 'box'
    requested_center: { lat: number; lon: number }
    grid_cell: { lat: number; lon: number }
    elevation_m: number | null
    timezone: string | null
    note: string | null
  }
  params: { percentile: number; min_days: number; method: Method; start_year: number; end_year: number }
  definition: string
  baseline: { start_year: number; end_year: number }
  reference: { period: [number, number]; frequency: number; days: number; mean_duration: number; intensity: number }
  summary: {
    total_events: number
    total_heatwave_days: number
    longest_event: HeatEvent | null
    most_intense_event: HeatEvent | null
    peak_temperature: HeatEvent | null
    years_analysed: number
    years_excluded: number[]
  }
  insights: { headline: string; items: Insight[]; caveats: string[] }
  trends: Record<MetricKey, TrendBlock>
  plot: {
    years: number[]
    valid: boolean[]
    metrics: Record<MetricKey, (number | null)[]>
    metric_meta: Record<MetricKey, { label: string; unit: string; long_unit: string }>
  }
  events: HeatEvent[]
  events_truncated: boolean
  data_quality: {
    total_days: number
    missing_in_source: number
    out_of_range_removed: number
    spikes_removed: number
    gaps_interpolated_days: number
    remaining_missing_days: number
    valid_fraction: number
    low_coverage_years: number[]
    rules: { plausible_range_c: [number, number]; spike_threshold_c: number; max_interpolated_gap_days: number; min_year_coverage: number }
  }
  meta: { source: string; data_through_year: number; cache: { analysis: string; raw: string }; store: string; computed_at: string }
}

export interface YearDetail {
  year: number
  dates: string[]
  tmax: (number | null)[]
  threshold: (number | null)[]
  in_heatwave: boolean[]
  events: HeatEvent[]
}

export interface Place {
  name: string
  admin1: string
  country: string
  lat: number
  lon: number
}
