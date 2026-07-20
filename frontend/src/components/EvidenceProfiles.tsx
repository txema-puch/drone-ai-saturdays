import { useMemo } from "react";

import type { ApproachCriterion, ApproachPathPoint } from "../api";
import { FEET_PER_MINUTE_PER_MPS, KNOTS_PER_MPS } from "../lib/aviation";

interface Props {
  path: ApproachPathPoint[];
  criteria: ApproachCriterion[];
  activeIndex: number | null;
}

interface Signal {
  key: keyof ApproachPathPoint;
  label: string;
  unit: string;
  criterion: string;
  convert?: (value: number) => number;
}

const SIGNALS: Signal[] = [
  { key: "cross_track_m", label: "Lateral path proxy", unit: "m", criterion: "lateral_path_proxy" },
  { key: "height_above_threshold_m", label: "Barometric height proxy", unit: "m", criterion: "barometric_path_proxy" },
  { key: "ground_speed_mps", label: "Observed ground speed", unit: "kt", criterion: "observed_ground_speed_envelope", convert: (value) => value * KNOTS_PER_MPS },
  { key: "vertical_rate_mps", label: "Observed vertical rate", unit: "ft/min", criterion: "observed_descent_rate", convert: (value) => value * FEET_PER_MINUTE_PER_MPS },
  { key: "track_offset_deg", label: "Runway track correction", unit: "°", criterion: "late_track_correction" },
];

const W = 720;
const LEFT = 154;
const RIGHT = 18;
const ROW_HEIGHT = 88;
const PLOT_PAD = 18;

function valueFor(point: ApproachPathPoint, signal: Signal): number | null {
  const raw = point[signal.key];
  if (typeof raw !== "number" || !Number.isFinite(raw)) return null;
  return signal.convert ? signal.convert(raw) : raw;
}

function reviewedAt(time: number, criterion: ApproachCriterion | undefined): boolean {
  return criterion?.status === "review_required" && criterion.evidence.some(
    (span) => time >= span.start_time && time <= span.end_time,
  );
}

export default function EvidenceProfiles({ path, criteria, activeIndex }: Props) {
  const pathTimes = path.flatMap((point) => point.time == null ? [] : [point.time]);
  const minTime = pathTimes.length ? Math.min(...pathTimes) : 0;
  const maxTime = pathTimes.length ? Math.max(...pathTimes) : 1;
  const timeSteps = pathTimes.slice(1).map((time, index) => time - pathTimes[index])
    .filter((step) => step > 0).sort((left, right) => left - right);
  const typicalStep = timeSteps.length ? timeSteps[Math.floor((timeSteps.length - 1) / 2)] : 1;
  const rows = useMemo(() => SIGNALS.map((signal) => {
    const points = path.flatMap((point, index) => {
      const value = valueFor(point, signal);
      const time = point.time;
      return value == null || time == null ? [] : [{ index, time, value }];
    });
    if (points.length < 2) return { signal, projected: [], criterion: undefined };
    const values = points.map((point) => point.value);
    let minValue = Math.min(...values);
    let maxValue = Math.max(...values);
    if (
      signal.key === "cross_track_m"
      || signal.key === "vertical_rate_mps"
      || signal.key === "track_offset_deg"
    ) {
      minValue = Math.min(minValue, 0);
      maxValue = Math.max(maxValue, 0);
    }
    const padding = Math.max((maxValue - minValue) * 0.12, 1);
    minValue -= padding;
    maxValue += padding;
    const projected = points.map((point) => ({
      ...point,
      x: LEFT + ((point.time - minTime) / Math.max(maxTime - minTime, 1)) * (W - LEFT - RIGHT),
      y: PLOT_PAD + ((maxValue - point.value) / Math.max(maxValue - minValue, 1)) * (ROW_HEIGHT - PLOT_PAD * 2),
    }));
    return {
      signal,
      projected,
      criterion: criteria.find((criterion) => criterion.name === signal.criterion),
    };
  }), [criteria, maxTime, minTime, path, typicalStep]);

  const activePoint = activeIndex == null ? null : path[activeIndex];

  return (
    <figure className="evidence-profiles">
      <svg
        viewBox={`0 0 ${W} ${ROW_HEIGHT * SIGNALS.length}`}
        role="img"
        aria-label="Synchronized generated signal profiles"
      >
        {rows.map(({ signal, projected, criterion }, rowIndex) => {
          const top = rowIndex * ROW_HEIGHT;
          const active = activePoint == null ? null : valueFor(activePoint, signal);
          const activeProjected = activeIndex == null
            ? null
            : projected.find((point) => point.index === activeIndex);
          return (
            <g key={signal.key} transform={`translate(0 ${top})`}>
              <line x1={LEFT} y1={ROW_HEIGHT - 1} x2={W - RIGHT} y2={ROW_HEIGHT - 1} className="evidence-profiles__divider" />
              <text x="12" y="31" className="evidence-profiles__label">{signal.label}</text>
              <text x="12" y="53" className="evidence-profiles__value">
                {active == null ? "Unavailable" : `${Math.round(active * 10) / 10} ${signal.unit}`}
              </text>
              <line x1={LEFT} y1={ROW_HEIGHT / 2} x2={W - RIGHT} y2={ROW_HEIGHT / 2} className="evidence-profiles__grid" />
              {projected.slice(1).map((point, index) => {
                const previous = projected[index];
                if (
                  point.index !== previous.index + 1
                  || point.time - previous.time > typicalStep * 1.5
                ) return null;
                const midpoint = (previous.time + point.time) / 2;
                return (
                  <line
                    key={`${signal.key}-${point.index}`}
                    x1={previous.x}
                    y1={previous.y}
                    x2={point.x}
                    y2={point.y}
                    className={reviewedAt(midpoint, criterion)
                      ? "evidence-profiles__line evidence-profiles__line--review"
                      : "evidence-profiles__line"}
                  />
                );
              })}
              {activeProjected && (
                <circle cx={activeProjected.x} cy={activeProjected.y} r="5" className="evidence-profiles__marker" />
              )}
            </g>
          );
        })}
      </svg>
      <figcaption className="sans">
        Each row shows a generated signal over the same evidence clock. Red sections are persistent review intervals; they are statistical evidence, not certified safety limits.
      </figcaption>
    </figure>
  );
}
