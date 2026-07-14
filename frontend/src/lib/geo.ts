/*
 * lat/lon → SVG projection. Adapted from SADAR's components/geo.ts (MIT,
 * devrup404). Kept the equirectangular cos(lat) longitude correction (more
 * faithful than the prototype's raw linear map) and exposed a reusable
 * projector so the trajectory line, the deviation dots, and the scrub marker
 * all share one coordinate transform.
 */

import type { ApproachPathPoint } from "../api";

export interface XY {
  x: number;
  y: number;
}

export interface Bounds {
  minLat: number;
  maxLat: number;
  minLon: number;
  maxLon: number;
  k: number; // cos(meanLat) longitude scale
}

export function geoBounds(points: { lat: number; lon: number }[]): Bounds {
  const lat0 = points.reduce((s, p) => s + p.lat, 0) / (points.length || 1);
  const k = Math.cos((lat0 * Math.PI) / 180);
  const lats = points.map((p) => p.lat);
  const lons = points.map((p) => p.lon);
  return {
    minLat: Math.min(...lats),
    maxLat: Math.max(...lats),
    minLon: Math.min(...lons),
    maxLon: Math.max(...lons),
    k,
  };
}

export interface Projector {
  x: (lon: number) => number;
  y: (lat: number) => number;
  project: (p: { lat: number; lon: number }) => XY;
  pxPerKm: number; // for drawing distance rings / a scale bar
}

const KM_PER_DEG_LAT = 111.32;

export function makeProjector(
  bounds: Bounds,
  width: number,
  height: number,
  pad = 28,
): Projector {
  const { minLat, maxLat, minLon, maxLon, k } = bounds;
  const spanX = (maxLon - minLon) * k || 1e-6;
  const spanY = maxLat - minLat || 1e-6;
  const scale = Math.min((width - 2 * pad) / spanX, (height - 2 * pad) / spanY);
  const offX = (width - scale * spanX) / 2;
  const offY = (height - scale * spanY) / 2;
  const x = (lon: number) => offX + (lon * k - minLon * k) * scale;
  const y = (lat: number) => height - (offY + (lat - minLat) * scale);
  // `scale` is px per degree of latitude (lon is pre-scaled by k); convert to px/km
  return { x, y, project: (p) => ({ x: x(p.lon), y: y(p.lat) }), pxPerKm: scale / KM_PER_DEG_LAT };
}

/** SVG polyline points attribute from projected coordinates. */
export function toPoints(points: { lat: number; lon: number }[], proj: Projector): string {
  return points.map((p) => `${proj.x(p.lon).toFixed(1)},${proj.y(p.lat).toFixed(1)}`).join(" ");
}

/** Legacy multi-track projector (SADAR-compatible), kept for reuse/tests. */
export function projectTracks(
  tracks: ApproachPathPoint[][],
  width: number,
  height: number,
  pad = 28,
): XY[][] {
  const all = tracks.flat();
  if (all.length === 0) return tracks.map(() => []);
  const proj = makeProjector(geoBounds(all), width, height, pad);
  return tracks.map((track) => track.map((p) => proj.project(p)));
}
