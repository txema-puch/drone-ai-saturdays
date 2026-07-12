import { useMemo } from "react";

import type { PathPoint } from "../api";
import { geoBounds, makeProjector, toPoints } from "../lib/geo";

interface Props {
  path: PathPoint[];
  reconstructed: PathPoint[];
  center: { lat: number; lon: number };
  stepScores: number[];
  stepThreshold: number;
  scrubIndex: number | null;
  overlayPath?: PathPoint[] | null; // perturbed path (what-if)
  contextPath?: { lat: number; lon: number }[] | null; // full trajectory (faint)
}

const W = 560;
const H = 360;
const PAD = 34;
const RING_KM = [5, 10, 20]; // distance rings around LEMD

// neighboring Madrid airfields. Filter D's 10km LEMD-proximity gate admits some traffic
// actually bound for these (D-010 limitation); showing them makes "lands at Cuatro Vientos,
// not LEMD" self-evident. Drawn only when they fall inside the current frame.
const NEIGHBORS: { name: string; lat: number; lon: number }[] = [
  { name: "LECU", lat: 40.3708, lon: -3.7853 }, // Cuatro Vientos
  { name: "LEGT", lat: 40.2942, lon: -3.7236 }, // Getafe
  { name: "LETO", lat: 40.4967, lon: -3.4458 }, // Torrejón
];

/** Case-viewer trajectory: the scored segment (actual vs model reconstruction, with amber
 *  deviation dots) drawn over the FULL operation as faint context, on a map with LEMD
 *  distance rings + a km scale bar — so an analyst reads true distance (a 0.1 km landing
 *  vs a 9 km fragment) instead of being misled by an unscaled, corner-pinned airport
 *  (D-014 sibling fix). Recolored from SADAR's RadarPlot to the C tokens. */
export default function TrajectoryMap({
  path,
  reconstructed,
  center,
  stepScores,
  stepThreshold,
  scrubIndex,
  overlayPath,
  contextPath,
}: Props) {
  const proj = useMemo(() => {
    // bounds fit the whole operation (context) + the airport, so a fragment shows in situ
    const ctx = contextPath && contextPath.length ? contextPath : path;
    const pts = [
      ...ctx.map((p) => ({ lat: p.lat, lon: p.lon })),
      ...(overlayPath ?? []).map((p) => ({ lat: p.lat, lon: p.lon })),
      center,
    ];
    return makeProjector(geoBounds(pts), W, H, PAD);
  }, [path, center, overlayPath, contextPath]);

  const cx = proj.x(center.lon);
  const cy = proj.y(center.lat);
  const marker = scrubIndex != null && path[scrubIndex] ? proj.project(path[scrubIndex]) : null;
  const hasContext = !!(contextPath && contextPath.length > path.length);

  // scale bar: pick a round km that's ~1/4 of the frame width
  const targetPx = (W - 2 * PAD) / 4;
  const niceKm = [1, 2, 5, 10, 20, 50, 100, 200].find((k) => k * proj.pxPerKm >= targetPx) ?? 200;
  const barPx = niceKm * proj.pxPerKm;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label="Operation trajectory over LEMD with distance rings; scored segment versus model reconstruction, deviation points marked."
      style={{ display: "block", width: "100%" }}
    >
      <rect width={W} height={H} fill="var(--map-bg)" />

      {/* LEMD distance rings */}
      {RING_KM.map((km) => {
        const r = km * proj.pxPerKm;
        if (r < 6 || r > W) return null;
        return (
          <g key={km}>
            <circle cx={cx} cy={cy} r={r} fill="none" stroke="var(--chart-grid)" strokeWidth={1} />
            <text x={cx} y={cy - r - 3} fill="var(--chart-muted)" fontSize={8.5} fontFamily="var(--sans)" textAnchor="middle">
              {km} km
            </text>
          </g>
        );
      })}

      {/* neighboring airfields (only when in-frame) */}
      {NEIGHBORS.map((f) => {
        const fx = proj.x(f.lon);
        const fy = proj.y(f.lat);
        if (fx < 4 || fx > W - 4 || fy < 10 || fy > H - 4) return null;
        return (
          <g key={f.name}>
            <circle cx={fx} cy={fy} r={3.5} fill="none" stroke="var(--chart-context)" strokeWidth={1} />
            <text x={fx + 7} y={fy + 3.5} fill="var(--chart-muted)" fontSize={9} fontFamily="var(--sans)">
              {f.name}
            </text>
          </g>
        );
      })}

      {/* airport reference */}
      <circle cx={cx} cy={cy} r={5} fill="none" stroke="var(--chart-muted)" strokeWidth={1.2} />
      <text x={cx + 9} y={cy + 4} fill="var(--chart-muted)" fontSize={10} fontFamily="var(--sans)">
        LEMD
      </text>

      {/* full-trajectory context (faint) */}
      {hasContext && (
        <polyline
          points={toPoints(contextPath!, proj)}
          fill="none"
          stroke="var(--chart-context)"
          strokeWidth={1.2}
          strokeLinejoin="round"
        />
      )}

      {/* model reconstruction (dashed blue) */}
      {reconstructed.length > 0 && (
        <polyline
          points={toPoints(reconstructed, proj)}
          fill="none"
          stroke="var(--blue)"
          strokeWidth={1.4}
          strokeDasharray="5 5"
          strokeLinejoin="round"
        />
      )}

      {/* the scored segment */}
      <polyline
        points={toPoints(path, proj)}
        fill="none"
        stroke="var(--actual)"
        strokeWidth={2.6}
        strokeLinejoin="round"
      />

      {/* what-if perturbed path */}
      {overlayPath && overlayPath.length > 0 && (
        <polyline
          points={toPoints(overlayPath, proj)}
          fill="none"
          stroke="var(--inject)"
          strokeWidth={2}
          strokeDasharray="5 4"
          strokeLinejoin="round"
        />
      )}

      {/* deviation dots — per-step RE above the step threshold */}
      {path.map((p, i) =>
        stepScores[i] != null && stepScores[i] >= stepThreshold ? (
          <circle key={i} cx={proj.x(p.lon)} cy={proj.y(p.lat)} r={3} fill="var(--amber)" />
        ) : null,
      )}

      {/* scrub marker */}
      {marker && (
        <circle cx={marker.x} cy={marker.y} r={6} fill="var(--ink)" stroke="var(--bg)" strokeWidth={2} />
      )}

      {/* scale bar */}
      <g transform={`translate(${PAD}, ${H - 16})`}>
        <line x1={0} y1={0} x2={barPx} y2={0} stroke="var(--chart-muted)" strokeWidth={1.5} />
        <line x1={0} y1={-3} x2={0} y2={3} stroke="var(--chart-muted)" strokeWidth={1.5} />
        <line x1={barPx} y1={-3} x2={barPx} y2={3} stroke="var(--chart-muted)" strokeWidth={1.5} />
        <text x={barPx / 2} y={-5} fill="var(--chart-muted)" fontSize={9} fontFamily="var(--sans)" textAnchor="middle">
          {niceKm} km
        </text>
      </g>
    </svg>
  );
}
