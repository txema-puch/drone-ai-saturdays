import { useState } from "react";

import type { ApproachCriterion, ApproachEvidenceSpan } from "../api";
import { humanize } from "../lib/approach";

interface Props {
  criteria: ApproachCriterion[];
  startTime: number;
  endTime: number;
  activeTime: number;
  runway: string;
  onTimeChange: (time: number) => void;
}

interface SelectedEvidence {
  criterion: ApproachCriterion;
  span: ApproachEvidenceSpan;
}

const KNOTS_PER_MPS = 1.943844;

function roundedKnots(value: number): number {
  return Math.round(value * KNOTS_PER_MPS);
}

function signed(value: number, unit: string): string {
  if (value < 0) return `−${Math.abs(value)} ${unit}`;
  if (value > 0) return `+${value} ${unit}`;
  return `0 ${unit}`;
}

function EvidenceExplanation({ selected, runway }: {
  selected: SelectedEvidence;
  runway: string;
}) {
  const { criterion, span } = selected;
  const duration = Math.max(0, span.end_time - span.start_time);
  const position = span.along_track_m == null
    ? "Position unavailable"
    : `${(span.along_track_m / 1_000).toFixed(1)} km before RWY ${runway}`;

  if (
    criterion.name === "observed_ground_speed_envelope"
    && span.value != null
    && span.limit != null
  ) {
    const observed = roundedKnots(span.value);
    const boundary = roundedKnots(span.limit);
    const lower = observed < boundary;
    return (
      <section className="evidence-explanation sans" aria-live="polite">
        <p className="eyebrow">Selected evidence interval</p>
        <h3>{lower ? "Lower-than-reference ground speed" : "Higher-than-reference ground speed"}</h3>
        <dl>
          <div><dt>Observed</dt><dd>{observed} kt</dd></div>
          <div><dt>Reference boundary</dt><dd>{boundary} kt</dd></div>
          <div><dt>Difference</dt><dd>{signed(observed - boundary, "kt")}</dd></div>
          <div><dt>Duration</dt><dd>{duration} {duration === 1 ? "second" : "seconds"}</dd></div>
          <div><dt>Position</dt><dd>{position}</dd></div>
        </dl>
        <p>This is a statistical comparison, not a safety-limit violation.</p>
      </section>
    );
  }

  const observed = span.value == null ? "Unavailable" : `${span.value} ${span.unit ?? ""}`.trim();
  const boundary = span.limit == null ? "Unavailable" : `${span.limit} ${span.unit ?? ""}`.trim();
  return (
    <section className="evidence-explanation sans" aria-live="polite">
      <p className="eyebrow">Selected evidence interval</p>
      <h3>{humanize(criterion.name)} crossing</h3>
      <dl>
        <div><dt>Observed</dt><dd>{observed}</dd></div>
        <div><dt>Reference boundary</dt><dd>{boundary}</dd></div>
        <div><dt>Duration</dt><dd>{duration} {duration === 1 ? "second" : "seconds"}</dd></div>
        <div><dt>Position</dt><dd>{position}</dd></div>
      </dl>
      <p>This is prototype evidence for analyst review, not a certified safety finding.</p>
    </section>
  );
}

export default function EvidenceTimeline({
  criteria,
  startTime,
  endTime,
  activeTime,
  runway,
  onTimeChange,
}: Props) {
  const [selected, setSelected] = useState<SelectedEvidence | null>(null);
  const duration = Math.max(1, endTime - startTime);
  const position = (time: number) => `${Math.max(0, Math.min(100, ((time - startTime) / duration) * 100))}%`;

  return (
    <div className="evidence-timeline">
      <label className="evidence-timeline__scrubber sans">
        <span>Evidence time</span>
        <input
          aria-label="Scrub synchronized map and evidence timeline"
          type="range"
          min={startTime}
          max={endTime}
          value={activeTime}
          onChange={(event) => {
            setSelected(null);
            onTimeChange(Number(event.target.value));
          }}
        />
      </label>
      <div className="evidence-timeline__lanes">
        {criteria.map((criterion) => (
          <div className="evidence-timeline__lane" key={criterion.name}>
            <span className="evidence-timeline__name sans">{humanize(criterion.name)}</span>
            <div className="evidence-timeline__track" aria-label={`${humanize(criterion.name)} evidence spans`}>
              {criterion.evidence.map((span, index) => {
                const isSelected = selected?.criterion === criterion && selected.span === span;
                return (
                  <button
                    className={`evidence-timeline__span evidence-timeline__span--${criterion.status}${isSelected ? " evidence-timeline__span--selected" : ""}`}
                    key={`${span.start_time}-${index}`}
                    style={{
                      left: position(span.start_time),
                      width: `max(8px, ${Math.max(1, ((span.end_time - span.start_time) / duration) * 100)}%)`,
                    }}
                    onClick={() => {
                      setSelected({ criterion, span });
                      onTimeChange(span.worst_time ?? span.start_time);
                    }}
                    aria-pressed={isSelected}
                    aria-label={`${humanize(criterion.name)} evidence from ${span.start_time} to ${span.end_time}; explain interval and show worst observation`}
                  />
                );
              })}
            </div>
          </div>
        ))}
      </div>
      {!selected && (
        <p className="evidence-timeline__hint sans">
          Select a colored interval to see its observed value, reference boundary, duration and position.
        </p>
      )}
      {selected && <EvidenceExplanation selected={selected} runway={runway} />}
    </div>
  );
}
