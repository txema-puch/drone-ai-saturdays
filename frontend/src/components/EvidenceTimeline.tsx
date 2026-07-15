import type { ApproachCriterion } from "../api";
import { humanize } from "../lib/approach";

interface Props {
  criteria: ApproachCriterion[];
  startTime: number;
  endTime: number;
  activeTime: number;
  onTimeChange: (time: number) => void;
}

export default function EvidenceTimeline({
  criteria,
  startTime,
  endTime,
  activeTime,
  onTimeChange,
}: Props) {
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
          onChange={(event) => onTimeChange(Number(event.target.value))}
        />
      </label>
      <div className="evidence-timeline__lanes">
        {criteria.map((criterion) => (
          <div className="evidence-timeline__lane" key={criterion.name}>
            <span className="evidence-timeline__name sans">{humanize(criterion.name)}</span>
            <div className="evidence-timeline__track" aria-label={`${humanize(criterion.name)} evidence spans`}>
              {criterion.evidence.map((span, index) => (
                <button
                  className={`evidence-timeline__span evidence-timeline__span--${criterion.status}`}
                  key={`${span.start_time}-${index}`}
                  style={{
                    left: position(span.start_time),
                    width: `max(8px, ${Math.max(1, ((span.end_time - span.start_time) / duration) * 100)}%)`,
                  }}
                  onClick={() => onTimeChange(span.worst_time ?? span.start_time)}
                  aria-label={`${humanize(criterion.name)} evidence from ${span.start_time} to ${span.end_time}; show worst observation`}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
