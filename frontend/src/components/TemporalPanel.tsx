import { useMemo, useRef } from "react";

export interface TemporalOverlay {
  series: number[]; // perturbed selected channel
  scores: number[]; // perturbed per-step RE
  onsetIndex: number;
}

interface Props {
  series: number[]; // base selected channel (e.g. altitude)
  seriesLabel: string; // "ALTITUDE (m)" style label for the top lane
  scores: number[]; // base per-step RE
  stepThreshold: number;
  scrubIndex: number | null;
  onScrub: (index: number | null) => void;
  overlay?: TemporalOverlay | null;
}

const TW = 1100;
const TH = 320;
const A0 = 18;
const A1 = 140; // top (selected channel) band
const R0 = 176;
const R1 = 300; // RE band

const minMax = (...arrs: number[][]) => {
  const flat = arrs.flat();
  return flat.length ? { lo: Math.min(...flat), hi: Math.max(...flat) } : { lo: 0, hi: 1 };
};

/** Temporal analysis: a selectable measured channel (top) stacked over reconstruction
 *  error (bottom) on a shared x-axis, with a linked scrub playhead. When a what-if result
 *  is supplied, the perturbed channel + perturbed RE are overlaid in magenta on the SAME
 *  axes (shared y-range) with an onset marker — so before/after is a direct read. Hover or
 *  arrow-key the chart to scrub; the parent drives the trajectory marker + readout. */
export default function TemporalPanel({
  series,
  seriesLabel,
  scores,
  stepThreshold,
  scrubIndex,
  onScrub,
  overlay,
}: Props) {
  const ref = useRef<SVGSVGElement>(null);
  const n = scores.length;

  const geo = useMemo(() => {
    const a = minMax(series, overlay ? overlay.series : []);
    const allScores = [...scores, ...(overlay ? overlay.scores : [])];
    const sorted = [...allScores].sort((x, y) => x - y);
    const p95 = sorted[Math.floor(0.95 * (sorted.length - 1))] ?? 1;
    const maxS = Math.max(p95, stepThreshold * 1.25, 1e-6);
    const tx = (i: number) => (i / Math.max(n - 1, 1)) * TW;
    const ay = (v: number) => A1 - ((v - a.lo) / (a.hi - a.lo || 1)) * (A1 - A0);
    const ry = (v: number) => R1 - (Math.min(v, maxS) / maxS) * (R1 - R0);
    const poly = (vals: number[], y: (v: number) => number) =>
      vals.map((v, i) => `${tx(i)},${y(v)}`).join(" ");
    return {
      tx,
      ay,
      ry,
      maxS,
      altPoly: poly(series, ay),
      rePoly: poly(scores, ry),
      ovAltPoly: overlay ? poly(overlay.series, ay) : "",
      ovRePoly: overlay ? poly(overlay.scores, ry) : "",
      peak: scores.indexOf(Math.max(...scores)),
    };
  }, [series, scores, stepThreshold, n, overlay]);

  function indexFromClientX(clientX: number): number {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return 0;
    const ratio = (clientX - rect.left) / rect.width;
    return Math.max(0, Math.min(n - 1, Math.round(ratio * (n - 1))));
  }

  function onKeyDown(e: React.KeyboardEvent<SVGSVGElement>) {
    if (n === 0) return;
    const cur = scrubIndex ?? 0;
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      onScrub(Math.max(0, cur - 1));
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      onScrub(Math.min(n - 1, cur + 1));
    } else if (e.key === "Home") {
      e.preventDefault();
      onScrub(0);
    } else if (e.key === "End") {
      e.preventDefault();
      onScrub(n - 1);
    } else if (e.key === "Escape") {
      onScrub(null);
    }
  }

  const phX = scrubIndex != null ? geo.tx(scrubIndex) : null;
  const onsetX = overlay ? geo.tx(overlay.onsetIndex) : null;

  return (
    <>
      <svg
        ref={ref}
        viewBox={`0 0 ${TW} ${TH}`}
        preserveAspectRatio="none"
        style={{ height: 320, width: "100%", display: "block", cursor: "crosshair" }}
        tabIndex={0}
        role="img"
        aria-label={`${seriesLabel} and reconstruction-error over time. Use left and right arrow keys to scrub through the segment.`}
        onMouseMove={(e) => onScrub(indexFromClientX(e.clientX))}
        onMouseLeave={() => onScrub(null)}
        onKeyDown={onKeyDown}
      >
        <rect width={TW} height={TH} fill="var(--map-bg)" />

        {/* top lane: selected channel */}
        <text x={6} y={14} fill="var(--mut)" fontSize={10} fontFamily="var(--sans)">
          {seriesLabel}
        </text>
        <polyline points={`0,${A1} ${geo.altPoly} ${TW},${A1}`} fill="rgba(111,143,181,.10)" />
        <polyline points={geo.altPoly} fill="none" stroke="var(--blue)" strokeWidth={1.8} />
        {overlay && (
          <polyline
            points={geo.ovAltPoly}
            fill="none"
            stroke="var(--inject)"
            strokeWidth={1.8}
            strokeDasharray="5 4"
          />
        )}

        {/* bottom lane: reconstruction error */}
        <text x={6} y={170} fill="var(--mut)" fontSize={10} fontFamily="var(--sans)">
          RECONSTRUCTION ERROR
        </text>
        <line
          x1={0}
          y1={geo.ry(stepThreshold)}
          x2={TW}
          y2={geo.ry(stepThreshold)}
          stroke="var(--chart-muted)"
          strokeWidth={1}
          strokeDasharray="5 4"
        />
        <text x={6} y={geo.ry(stepThreshold) - 4} fill="var(--mut)" fontSize={9} fontFamily="var(--sans)">
          step threshold
        </text>
        <polyline points={`0,${R1} ${geo.rePoly} ${TW},${R1}`} fill="rgba(224,169,59,.12)" />
        <polyline points={geo.rePoly} fill="none" stroke="var(--amber)" strokeWidth={2} />
        {overlay && (
          <polyline
            points={geo.ovRePoly}
            fill="none"
            stroke="var(--inject)"
            strokeWidth={2}
            strokeDasharray="5 4"
          />
        )}

        {/* onset marker (what-if) */}
        {onsetX != null && (
          <line x1={onsetX} y1={A0} x2={onsetX} y2={R1} stroke="var(--inject)" strokeWidth={1} strokeDasharray="2 3" />
        )}

        {/* peak + scrub playhead */}
        {geo.peak >= 0 && (
          <line x1={geo.tx(geo.peak)} y1={A0} x2={geo.tx(geo.peak)} y2={R1} stroke="var(--chart-grid)" strokeWidth={1} />
        )}
        {phX != null && <line x1={phX} y1={A0} x2={phX} y2={R1} stroke="var(--ink)" strokeWidth={1} />}
      </svg>

      {/* screen-reader data-table fallback (DESIGN.md a11y fix #5). Wrapped in a div.sr-only —
          a table's own box ignores height:1px + overflow:hidden, so the clip lives on the div. */}
      <div className="sr-only">
        <table aria-label="Per-step channel value and reconstruction error">
          <caption>Per-step {seriesLabel} and reconstruction error</caption>
          <thead>
            <tr>
              <th scope="col">Step</th>
              <th scope="col">{seriesLabel}</th>
              <th scope="col">Reconstruction error</th>
            </tr>
          </thead>
          <tbody>
            {scores.map((s, i) => (
              <tr key={i}>
                <td>{i}</td>
                <td>{Math.round(series[i] ?? 0)}</td>
                <td>{s.toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
