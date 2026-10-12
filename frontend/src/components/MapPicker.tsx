import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { CircleMarker, MapContainer, Rectangle, TileLayer, useMap, useMapEvents } from 'react-leaflet'
import type { Region } from '../types'

export type MapMode = 'point' | 'box'

interface Props {
  region: Region
  mode: MapMode
  onPoint: (lat: number, lon: number) => void
  onBox: (minLat: number, minLon: number, maxLat: number, maxLon: number) => void
}

const round = (x: number) => Math.round(x * 100) / 100

function Interactions({ mode, onPoint, onBox }: Omit<Props, 'region'>) {
  const map = useMap()
  const anchor = useRef<L.LatLng | null>(null)
  const [draft, setDraft] = useState<L.LatLngBounds | null>(null)

  // While drawing a box, dragging must draw instead of panning the map.
  useEffect(() => {
    if (mode === 'box') map.dragging.disable()
    else map.dragging.enable()
    return () => {
      map.dragging.enable()
    }
  }, [mode, map])

  useMapEvents({
    click(e) {
      if (mode === 'point') {
        const p = e.latlng.wrap()
        onPoint(round(p.lat), round(p.lng))
      }
    },
    mousedown(e) {
      if (mode === 'box') {
        anchor.current = e.latlng.wrap()
        setDraft(L.latLngBounds(e.latlng, e.latlng))
      }
    },
    mousemove(e) {
      if (mode === 'box' && anchor.current) setDraft(L.latLngBounds(anchor.current, e.latlng.wrap()))
    },
    mouseup(e) {
      if (mode === 'box' && anchor.current) {
        const b = L.latLngBounds(anchor.current, e.latlng.wrap())
        anchor.current = null
        setDraft(null)
        if (b.getNorth() - b.getSouth() >= 0.25 && b.getEast() - b.getWest() >= 0.25) {
          onBox(round(b.getSouth()), round(b.getWest()), round(b.getNorth()), round(b.getEast()))
        }
      }
    },
  })
  return draft ? <Rectangle bounds={draft} pathOptions={{ color: '#eb6834', weight: 2, dashArray: '5 4', fillOpacity: 0.12 }} /> : null
}

function Recenter({ region }: { region: Region }) {
  const map = useMap()
  const key = region.kind === 'point' ? `${region.lat},${region.lon}` : `${region.minLat},${region.minLon},${region.maxLat},${region.maxLon}`
  const last = useRef('')
  useEffect(() => {
    if (key === last.current) return
    last.current = key
    if (region.kind === 'point') map.setView([region.lat, region.lon], Math.max(map.getZoom(), 5), { animate: true })
    else map.fitBounds([[region.minLat, region.minLon], [region.maxLat, region.maxLon]], { padding: [24, 24], animate: true })
  }, [key, region, map])
  return null
}

export default function MapPicker({ region, mode, onPoint, onBox }: Props) {
  const center: [number, number] = region.kind === 'point' ? [region.lat, region.lon] : [(region.minLat + region.maxLat) / 2, (region.minLon + region.maxLon) / 2]
  return (
    <div className={`map-wrap ${mode === 'box' ? 'drawing' : ''}`}>
      <MapContainer center={center} zoom={5} minZoom={2} worldCopyJump scrollWheelZoom={false} style={{ height: '100%', width: '100%' }}>
        <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" maxZoom={12} />
        <Interactions mode={mode} onPoint={onPoint} onBox={onBox} />
        <Recenter region={region} />
        {region.kind === 'point' ? (
          <CircleMarker center={[region.lat, region.lon]} radius={9} pathOptions={{ color: '#ffffff', weight: 2, fillColor: '#eb6834', fillOpacity: 1 }} />
        ) : (
          <Rectangle bounds={[[region.minLat, region.minLon], [region.maxLat, region.maxLon]]} pathOptions={{ color: '#eb6834', weight: 2, fillOpacity: 0.15 }} />
        )}
      </MapContainer>
    </div>
  )
}
