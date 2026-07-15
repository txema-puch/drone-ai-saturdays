import type { ApproachStatus } from "../api";
import { STATUS_COPY } from "../lib/approach";

interface Props {
  status: ApproachStatus;
  compact?: boolean;
}

export default function ApproachStatus({ status, compact = false }: Props) {
  const copy = STATUS_COPY[status];
  return (
    <span className={`approach-status approach-status--${status}`}>
      <span aria-hidden="true" className="approach-status__mark" />
      <span>{copy.label}</span>
      {!compact && <span className="sr-only">. {copy.explanation}</span>}
    </span>
  );
}
