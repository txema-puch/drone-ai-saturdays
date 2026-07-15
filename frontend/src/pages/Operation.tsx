import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { getApproachOperation, type ApproachOperation } from "../api";
import ApproachStatus from "../components/ApproachStatus";
import { formatCoverage, formatTime, humanize } from "../lib/approach";

export default function Operation() {
  const { operationRef = "" } = useParams();
  const [operation, setOperation] = useState<ApproachOperation | null>(null);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setOperation(null);
    setError(false);
    getApproachOperation(operationRef, controller.signal).then(setOperation).catch((reason: unknown) => {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setError(true);
    });
    return () => controller.abort();
  }, [operationRef, retry]);

  if (error) return (
    <main className="workspace"><div className="state-panel state-panel--page" role="alert">
      <h1>Operation context unavailable</h1>
      <p>The attempt queue remains available.</p>
      <div className="state-actions"><button onClick={() => setRetry((value) => value + 1)}>Retry</button><Link to="/">Return to attempts</Link></div>
    </div></main>
  );

  if (!operation) return <main className="workspace dossier-loading" aria-busy="true"><div className="loading-line loading-line--title" /><div className="loading-panel" /></main>;

  return (
    <main className="workspace operation-workspace">
      <nav className="breadcrumb sans" aria-label="Breadcrumb"><Link to="/">Attempts</Link><span>/</span><span aria-current="page">Operation {operation.operation_ref}</span></nav>
      <header className="workspace-header">
        <div><p className="eyebrow">Secondary context</p><h1>Observed operation</h1><p className="workspace-subtitle sans">One source operation may contain multiple independently assessed approach attempts.</p></div>
        <div className="cohort-summary sans"><span>Operation reference</span><b className="mono">{operation.operation_ref}</b><small>{operation.attempts.length} attempts</small></div>
      </header>
      {operation.attempts.length ? (
        <ol className="operation-attempts">
          {operation.attempts.map((attempt, index) => (
            <li key={attempt.attempt_id}>
              <Link to={`/approaches/${encodeURIComponent(attempt.attempt_id)}`}>
                <span className="operation-index mono">{String(index + 1).padStart(2, "0")}</span>
                <span><ApproachStatus status={attempt.status} compact /><small className="mono">{attempt.attempt_id}</small></span>
                <span><b>{attempt.runway ?? attempt.direction ?? "Unknown runway"}</b><small>{humanize(attempt.outcome)}</small></span>
                <span><b>{attempt.failed_criteria.length ? attempt.failed_criteria.map(humanize).join(", ") : "No persistent crossing"}</b><small>{formatCoverage(attempt.coverage, attempt.observed_samples)}</small></span>
                <time>{formatTime(attempt.start_time)}</time>
              </Link>
            </li>
          ))}
        </ol>
      ) : <div className="state-panel"><h2>No approach attempts extracted</h2><p>The operation is retained as reconstruction context, but it did not enter the supported final corridor.</p><Link to="/">Return to loaded attempts</Link></div>}
    </main>
  );
}
