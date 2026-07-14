import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { getOperation, hasApiStatus, type OperationSummary } from "../api";
import Stamp from "../components/Stamp";
import { aircraftOf, parseEpoch, pctColor, scoreColor } from "../lib/format";
import "./operation.css";

export default function Operation() {
  const { operationRef = "" } = useParams();
  const navigate = useNavigate();
  const [operation, setOperation] = useState<OperationSummary | null>(null);
  const [error, setError] = useState<"none" | "missing" | "down">("none");

  useEffect(() => {
    const ctrl = new AbortController();
    setOperation(null);
    setError("none");
    getOperation(operationRef, ctrl.signal)
      .then(setOperation)
      .catch((responseError) => {
        if (responseError?.name === "AbortError") return;
        setError(hasApiStatus(responseError, 404) ? "missing" : "down");
      });
    return () => ctrl.abort();
  }, [operationRef]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") navigate("/");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);

  if (error !== "none") {
    return (
      <div className="op-state sans">
        <div className="big">{error === "missing" ? "Operation not found" : "Cannot reach the audit service"}</div>
        <p>{error === "missing" ? "This operation reference is not in the current audit bundle." : "The audit service is not responding."}</p>
        <button onClick={() => navigate("/")}>Back to operation queue</button>
      </div>
    );
  }

  if (!operation) {
    return <div className="op-state sans" aria-busy="true"><div className="big">Loading operation…</div></div>;
  }

  const behavioralWorst = operation.behavioral_worst_case_id == null
    ? null
    : operation.segments.find((segment) => segment.case_id === operation.behavioral_worst_case_id) ?? null;

  return (
    <main className="op-page">
      <header className="op-header">
        <nav className="op-crumb sans" aria-label="Breadcrumb"><a href="/" onClick={(event) => { event.preventDefault(); navigate("/"); }}>‹ Conformance Audit — LEMD</a><span>/</span><span>Operation</span></nav>
        <div className="op-title-row">
          <div>
            <h1>Operation review</h1>
            <div className="op-ref mono">{operation.operation_ref}</div>
            <div className="op-meta sans">aircraft {aircraftOf(operation.worst_segment_id)} · {parseEpoch(operation.worst_segment_id)}</div>
          </div>
          <div className="op-worst">
            <span className="microlabel">Behavioral review score</span>
            {behavioralWorst ? <>
              <strong style={{ color: scoreColor(behavioralWorst.score) }}>{behavioralWorst.score.toFixed(2)}</strong>
              <span className="sans" style={{ color: pctColor(behavioralWorst.pct) }}>{Math.round(behavioralWorst.pct)}th percentile · {behavioralWorst.band}</span>
            </> : <strong className="op-abstain">Not assessable</strong>}
            <small className="sans">Raw worst: {operation.worst_case_ref} · RE {operation.worst_score.toFixed(2)}</small>
          </div>
        </div>
      </header>

      <section className="op-summary sans" aria-label="Operation summary">
        <div><span>Segments</span><b>{operation.segment_count}</b></div>
        <div><span>Flagged</span><b>{operation.flagged_segment_count}</b></div>
        <div><span>Terminal</span><b>{operation.terminal_segment_count}</b></div>
        <div><span>Truncated</span><b>{operation.truncated_segment_count}</b></div>
        <div><span>Reviewable</span><b>{operation.reviewable_segment_count}</b></div>
        <div><span>Not assessable</span><b>{operation.not_assessable_segment_count}</b></div>
        <div><span>Labels</span><b>{operation.labels_seen.join(", ")}</b></div>
        <div><span>Data quality</span><b>{operation.data_quality_summary}</b></div>
      </section>

      <section className="op-evidence">
        <div className="op-section-head">
          <div>
            <h2>Segment evidence</h2>
            <p className="sans">Behavioral review uses only reviewable segment evidence. Raw worst remains {operation.worst_case_ref}; segment scores are never added together.</p>
          </div>
          <div className="op-signals sans">
            {operation.has_confirmed_event && <span>confirmed event present</span>}
            {operation.has_model_flag_unlabeled && <span>unlabeled model flag</span>}
            {operation.data_quality_segment_count > 0 && <span>{operation.data_quality_segment_count} data-quality</span>}
            {operation.coverage_limited_segment_count > 0 && <span>{operation.coverage_limited_segment_count} coverage-limited</span>}
          </div>
        </div>

        <div className="op-table-wrap">
          <table className="op-table sans">
            <thead><tr><th>Case</th><th>Segment</th><th>Model</th><th>Assessment</th><th>Percentile</th><th>Score</th><th>Label</th><th><span className="sr-only">Action</span></th></tr></thead>
            <tbody>
              {operation.segments.map((segment) => (
                <tr key={segment.case_id} className={segment.case_ref === operation.worst_case_ref ? "worst" : ""}>
                  <td><b className="mono">{segment.case_ref}</b>{segment.case_ref === operation.worst_case_ref && <small>Worst segment</small>}</td>
                  <td><span className="mono">{segment.segment_id}</span><small>{parseEpoch(segment.segment_id)}</small></td>
                  <td><span className={segment.anomalous ? "op-flagged" : "op-below"}>{segment.anomalous ? "Flagged" : "Below threshold"}</span></td>
                  <td><span className={`op-assessment op-assessment--${segment.review_lane}`}>{segment.assessment_state.replace(/_/g, " ")}</span><small>{segment.behavioral_verdict.replace(/_/g, " ")}</small></td>
                  <td style={{ color: pctColor(segment.pct) }}>{Math.round(segment.pct)}th</td>
                  <td className="op-score" style={{ color: scoreColor(segment.score) }}>{segment.score.toFixed(2)}</td>
                  <td><Stamp label={segment.label} /></td>
                  <td className="op-action">{segment.has_case ? <button onClick={() => navigate(`/case/${segment.case_id}`)} aria-label={`Open ${segment.case_ref} segment case file`}>Open case</button> : <span>Evidence only</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <footer className="op-foot sans">{operation.operation_ref} · {operation.segment_count} independently scored segments</footer>
    </main>
  );
}
