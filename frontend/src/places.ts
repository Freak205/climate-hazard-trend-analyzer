import type { Place } from './types'
import presets from '../../shared/presets.json'

/**
 * Quick-pick places (shared with the backend cache seeder via shared/presets.json).
 * Open-Meteo's geocoder resolves cities but not states, so states/regions are
 * offered as approximate centre points (data is the ERA5 0.25 degree cell at
 * that point, not a state-wide average).
 */
export const CITY_PRESETS: Place[] = presets.cities
export const STATE_PRESETS: Place[] = presets.states
export const ALL_PRESETS = [...CITY_PRESETS, ...STATE_PRESETS]

export function placeLabel(p: Place): string {
  return [p.name, p.admin1 && p.admin1 !== p.name ? p.admin1 : '', p.country].filter(Boolean).join(', ')
}
