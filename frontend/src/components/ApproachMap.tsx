import { useMemo } from "react";

import type { ApproachPathPoint } from "../api";
import { geoBounds, makeProjector } from "../lib/geo";

interface Props {
  path: ApproachPathPoint[];
  activeIndex: number | null;
  runway?: string | null;
}

const W = 720;
const H = 420;
const PAD = 36;

export default function ApproachMap({ path, activeIndex, runway }: Props) {
  const relative = path.length > 1 && path.every(
    (point) => Number.isFinite(point.along_track_m) && Number.isFinite(point.cross_track_m),
  );
  const projected = useMemo(() => {
    if (!path.length) return [];
    if (relative) {
      const along = path.map((point) => point.along_track_m as number);
      const cross = path.map((point) => point.cross_track_m as number);
      const maxAlong = Math.max(...along, 1);
      const maxCross = Math.max(...cross.map(Math.abs), 500);
      return path.map((point) => ({
        x: W / 2 + ((point.cross_track_m as number) / maxCross) * (W / 2 - PAD),
        y: H - PAD - ((point.along_track_m as number) / maxAlong) * (H - PAD * 2),
      }));
    }
    const projector = makeProjector(geoBounds(path), W, H, PAD);
    return path.map((point) => projector.project(point));
  }, [path, relative]);
  const marker = activeIndex == null ? null : projected[activeIndex];
  const points = projected.map((point) => `${point.x},${point.y}`).join(" ");

  return (
    <figure className="evidence-map">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={relative
          ? `Observed trajectory relative to runway ${runway ?? "direction unavailable"}`
          : `Observed approach trajectory; runway-relative coordinates unavailable`}
      >
        <rect width={W} height={H} fill="var(--map-bg)" />
        {relative ? (
          <>
            <line x1={W / 2} y1={PAD} x2={W / 2} y2={H - PAD} className="evidence-map__axis" />
            <line x1={W / 2 - 30} y1={H - PAD} x2={W / 2 + 30} y2={H - PAD} className="evidence-map__runway" />
            <text x={W / 2 + 38} y={H - PAD + 4} className="evidence-map__label">RWY {runway ?? "?"}</text>
            <text x={PAD} y={PAD - 10} className="evidence-map__label">runway-relative evidence</text>
          </>
        ) : (
          <text x={PAD} y={PAD - 10} className="evidence-map__label">geographic evidence · runway-relative values unavailable</text>
        )}
        <polyline points={points} className="evidence-map__path" />
        {projected[0] && <circle cx={projected[0].x} cy={projected[0].y} r={4} className="evidence-map__start" />}
        {projected[projected.length - 1] && <circle cx={projected[projected.length - 1].x} cy={projected[projected.length - 1].y} r={4} className="evidence-map__end" />}
        {marker && <circle cx={marker.x} cy={marker.y} r={7} className="evidence-map__marker" />}
      </svg>
      <figcaption className="sans">
        Observed positions only. The line is evidence coverage, not a certified flight path.
      </figcaption>
    </figure>
  );
}
