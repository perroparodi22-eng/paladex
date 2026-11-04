// Offline map of the honey regions: react-leaflet with NO tile layer (country shapes bundled with the
// app, as on /paesi). One circle per NASA POWER point, coloured by its region's main automatic signal of
// the last 12 months: filled when the signal touches the last 3 months, a ring when it is older.
// Loaded lazily by the page (Leaflet needs a browser).
import type { Feature, FeatureCollection, Geometry } from 'geojson'
import type { LatLngBoundsExpression, PathOptions } from 'leaflet'
import { useMemo } from 'react'
import { CircleMarker, GeoJSON, MapContainer, Tooltip } from 'react-leaflet'
import { feature } from 'topojson-client'
import type { GeometryCollection, Topology } from 'topojson-specification'
import worldData from 'world-atlas/countries-110m.json'
import { useI18n } from '@/i18n'
import { fmtPeriod } from '@/lib/format'
import { CONDITION_COLORS, countryOf, fmtAnomaly, fmtPctOfNormal, regionName } from './format'
import type { HarvestRegion } from './types'
import '@/components/countries/map.css'

type AtlasProps = { name: string }
const topo = worldData as unknown as Topology<{ countries: GeometryCollection<AtlasProps> }>
const WORLD = feature(topo, topo.objects.countries) as FeatureCollection<Geometry, AtlasProps>

/** Rings crossing the antimeridian (Russia, Fiji) would streak across the map: shift their western points. */
function unwrapRing(ring: number[][]): number[][] {
  const crosses = ring.some((p, i) => i > 0 && Math.abs(p[0] - ring[i - 1][0]) > 180)
  return crosses ? ring.map(([x, y]) => [x < 0 ? x + 360 : x, y]) : ring
}
function unwrap(g: Geometry): Geometry {
  if (g.type === 'Polygon') return { ...g, coordinates: g.coordinates.map(unwrapRing) }
  if (g.type === 'MultiPolygon') return { ...g, coordinates: g.coordinates.map((poly) => poly.map(unwrapRing)) }
  return g
}
const LAND: FeatureCollection = {
  ...WORLD,
  features: WORLD.features.filter((f) => f.id !== '010').map((f) => ({ ...f, geometry: unwrap(f.geometry) })) as Feature[],
}
const LAND_STYLE: PathOptions = { fillColor: '#F3EFE3', fillOpacity: 1, color: '#FFFFFF', weight: 0.8, interactive: false }
const MAX_BOUNDS: LatLngBoundsExpression = [[-75, -230], [88, 230]]

export interface RegionMapProps {
  regions: HarvestRegion[]
  /** region keys shown (country / signal filters); the others are drawn faint */
  visible: Set<string>
  selected: string
  onSelect: (key: string) => void
  height: number
}

export default function RegionMap({ regions, visible, selected, onSelect, height }: RegionMapProps) {
  const { t, lang } = useI18n()
  const bounds = useMemo<LatLngBoundsExpression>(() => {
    const shown = regions.filter((r) => visible.has(r.key))
    const pts = (shown.length ? shown : regions).flatMap((r) => r.points)
    if (!pts.length) return [[-50, -130], [62, 180]]
    const lats = pts.map((p) => p.lat)
    const lons = pts.map((p) => p.lon)
    const pad = shown.length && shown.length < regions.length ? 3 : 6
    return [[Math.min(...lats) - pad, Math.min(...lons) - pad], [Math.max(...lats) + pad, Math.max(...lons) + pad]]
  }, [regions, visible])

  return (
    <MapContainer
      key={JSON.stringify(bounds)}
      className="pdx-map"
      bounds={bounds}
      maxBounds={MAX_BOUNDS}
      maxBoundsViscosity={0.8}
      zoomSnap={0.25}
      zoomDelta={0.5}
      minZoom={0}
      maxZoom={8}
      scrollWheelZoom={false}
      attributionControl={false}
      worldCopyJump={false}
      style={{ height, width: '100%' }}
    >
      <GeoJSON data={LAND} style={() => LAND_STYLE} />
      {regions.flatMap((r) => r.points.map((p) => {
        const shown = visible.has(r.key)
        const color = CONDITION_COLORS[r.condition]
        const flagged = r.condition !== 'normal' && r.condition !== 'no_data'
        const hollow = flagged && !r.condition_recent
        const isSel = r.key === selected
        return (
          <CircleMarker
            key={p.key}
            center={[p.lat, p.lon]}
            radius={isSel ? 9 : flagged ? 7 : 5.5}
            pathOptions={{
              color: isSel ? '#0E2A1F' : color, weight: isSel ? 3 : hollow ? 2.5 : 1.2,
              fillColor: hollow ? '#FFFFFF' : color, fillOpacity: shown ? (hollow ? 0.95 : 0.9) : 0.25,
              opacity: shown ? 1 : 0.35,
            }}
            eventHandlers={{ click: () => onSelect(r.key) }}
          >
            <Tooltip direction="top" offset={[0, -6]} className="pdx-map-tip" opacity={1}>
              <div className="t-name">{regionName(r, lang)}</div>
              <div className="t-muted" style={{ marginTop: 0 }}>{countryOf(r, lang)} · {p.name}</div>
              <div className="t-row"><span className="t-label">{t(`harvest.cond.${r.condition}`)}</span>
                {flagged && <span className="t-label">{t(r.condition_recent ? 'harvest.cond.recent' : 'harvest.cond.earlier')}</span>}
              </div>
              {r.has_data ? (
                <div className="t-sep">
                  <div className="t-label">{t('harvest.map.tipMonths')}</div>
                  {r.recent.map((m) => (
                    <div key={m.period_label} className="t-row">
                      <span className="t-label">{fmtPeriod(m.period_label, lang)}{m.data_status === 'provisional' ? ` · ${t('harvest.table.provisional')}` : ''}</span>
                      <span className="t-val" style={{ fontSize: 13 }}>
                        {m.points_with_data ? `${fmtAnomaly(m.temp_anomaly_c, lang)} · ${fmtPctOfNormal(m.precip_pct, lang)}` : '—'}
                      </span>
                    </div>
                  ))}
                </div>
              ) : <div className="t-muted">{t('harvest.map.tipNoData')}</div>}
              <div className="t-sep t-cta">{t('harvest.map.tipClick')} →</div>
            </Tooltip>
          </CircleMarker>
        )
      }))}
    </MapContainer>
  )
}
