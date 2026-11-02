// Offline world choropleth: react-leaflet with NO tile layer. Country shapes come from the bundled
// Natural Earth 1:110m TopoJSON (world-atlas); its ISO numeric ids are matched to our countries
// through their M49 code. Grey = no data. Hover: sticky tooltip; click: country profile.
import type { Feature, FeatureCollection, Geometry } from 'geojson'
import type { GeoJSON as LeafletGeoJSON, Layer, LeafletMouseEvent, Path, PathOptions } from 'leaflet'
import { useCallback, useEffect, useMemo, useRef } from 'react'
import { GeoJSON, MapContainer } from 'react-leaflet'
import { feature } from 'topojson-client'
import type { GeometryCollection, Topology } from 'topojson-specification'
import worldData from 'world-atlas/countries-110m.json'
import { BORDER, NO_DATA } from './choropleth'
import type { CountryListItem } from './types'
import './map.css'

type AtlasProps = { name: string }
type AtlasFeature = Feature<Geometry, AtlasProps>

const topo = worldData as unknown as Topology<{ countries: GeometryCollection<AtlasProps> }>
const WORLD = feature(topo, topo.objects.countries) as FeatureCollection<Geometry, AtlasProps>

/** Rings crossing the antimeridian (Russia's Chukotka, Fiji) jump from +180 to -180 and would be
 * drawn as streaks across the whole map: shift their western points by +360° instead. */
function unwrapRing(ring: number[][]): number[][] {
  const crosses = ring.some((p, i) => i > 0 && Math.abs(p[0] - ring[i - 1][0]) > 180)
  return crosses ? ring.map(([x, y]) => [x < 0 ? x + 360 : x, y]) : ring
}

function unwrap(g: Geometry): Geometry {
  if (g.type === 'Polygon') return { ...g, coordinates: g.coordinates.map(unwrapRing) }
  if (g.type === 'MultiPolygon') return { ...g, coordinates: g.coordinates.map((poly) => poly.map(unwrapRing)) }
  return g
}

// Antarctica (010) is dropped: no honey trade, and it would take a third of the map.
const FEATURES: FeatureCollection<Geometry, AtlasProps> = {
  ...WORLD,
  features: WORLD.features.filter((f) => f.id !== '010').map((f) => ({ ...f, geometry: unwrap(f.geometry) })),
}

const BOUNDS: [[number, number], [number, number]] = [[-56, -170], [80, 190]]
const MAX_BOUNDS: [[number, number], [number, number]] = [[-75, -230], [88, 230]]

export interface WorldMapProps {
  items: CountryListItem[]
  /** fill colour of a tracked country (already resolved for the current metric) */
  fillOf: (c: CountryListItem) => string
  /** HTML of the tooltip of a tracked country (strings must be escaped by the caller) */
  tooltipOf: (c: CountryListItem) => string
  onSelect: (iso3: string) => void
  /** changes whenever the colouring changes (metric, data) */
  styleKey: string
  height?: number
}

export function WorldMap({ items, fillOf, tooltipOf, onSelect, styleKey, height = 540 }: WorldMapProps) {
  const byM49 = useMemo(() => {
    const m = new Map<number, CountryListItem>()
    for (const c of items) if (c.m49 !== null) m.set(c.m49, c)
    return m
  }, [items])

  // Leaflet keeps the handlers it was given; refs make them read the latest props.
  const latest = useRef({ byM49, fillOf, tooltipOf, onSelect })
  latest.current = { byM49, fillOf, tooltipOf, onSelect }
  const geoRef = useRef<LeafletGeoJSON | null>(null)

  const itemOf = (f: AtlasFeature | undefined) => (f?.id !== undefined ? latest.current.byM49.get(Number(f.id)) : undefined)

  const style = useCallback((f?: AtlasFeature): PathOptions => {
    const c = itemOf(f)
    return {
      fillColor: c ? latest.current.fillOf(c) : NO_DATA,
      fillOpacity: 1,
      color: BORDER,
      weight: 0.7,
      interactive: Boolean(c),
    }
  }, [])

  useEffect(() => {
    geoRef.current?.setStyle(style as (f?: Feature) => PathOptions)
  }, [styleKey, style])

  const onEach = useCallback((f: AtlasFeature, layer: Layer) => {
    const c = itemOf(f)
    if (!c) return
    layer.bindTooltip(() => {
      const cur = itemOf(f)
      return cur ? latest.current.tooltipOf(cur) : ''
    }, { sticky: true, direction: 'top', offset: [0, -10], className: 'pdx-map-tip', opacity: 1 })
    layer.on({
      mouseover: (e: LeafletMouseEvent) => {
        const p = e.target as Path
        p.setStyle({ weight: 1.8, color: '#0E2A1F' })
        p.bringToFront()
      },
      mouseout: (e: LeafletMouseEvent) => geoRef.current?.resetStyle(e.target as Path),
      click: () => {
        const cur = itemOf(f)
        if (cur) latest.current.onSelect(cur.iso3)
      },
    })
  }, [])

  return (
    <MapContainer
      className="pdx-map"
      bounds={BOUNDS}
      maxBounds={MAX_BOUNDS}
      maxBoundsViscosity={0.8}
      zoomSnap={0.25}
      zoomDelta={0.5}
      minZoom={1}
      maxZoom={6}
      scrollWheelZoom={false}
      attributionControl={false}
      worldCopyJump={false}
      style={{ height, width: '100%' }}
    >
      <GeoJSON
        key={byM49.size}
        ref={geoRef}
        data={FEATURES as FeatureCollection}
        style={style as (f?: Feature) => PathOptions}
        onEachFeature={onEach as (f: Feature, l: Layer) => void}
      />
    </MapContainer>
  )
}

export function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]!))
}
