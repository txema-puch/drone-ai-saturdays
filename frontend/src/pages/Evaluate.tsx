import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import {
  ApiError,
  evaluateApproachFile,
  getHealth,
  type ApproachUploadResponse,
  type Health,
} from "../api";
import ApproachStatus from "../components/ApproachStatus";
import { formatCoverage, formatTime, humanize } from "../lib/approach";

type Phase = "checking" | "idle" | "uploading" | "success" | "error";

function downloadEvidence(result: ApproachUploadResponse) {
  const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `sadar-approach-evidence-${result.upload_sha256?.slice(0, 12) ?? "export"}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function Evaluate() {
  const [phase, setPhase] = useState<Phase>("checking");
  const [health, setHealth] = useState<Health | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ApproachUploadResponse | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const errorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal).then((value) => {
      setHealth(value);
      setPhase("idle");
    }).catch((reason: unknown) => {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setError(reason instanceof Error ? reason : new Error("Capability check failed."));
      setPhase("error");
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (phase === "error") errorRef.current?.focus();
  }, [phase]);

  const enabled = health?.evaluation_enabled !== false && health?.mode === "approach-screening";

  function chooseFile(selected: File | null) {
    setFile(selected);
    setResult(null);
    setError(null);
    setPhase("idle");
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file || !enabled) return;
    const extension = file.name.split(".").pop()?.toLowerCase();
    if (!extension || !["csv", "parquet"].includes(extension)) {
      setError(new ApiError(0, "unsupported_file", "Choose a .csv or .parquet file.", [
        { field: "file", message: "Supported extensions are .csv and .parquet." },
      ]));
      setPhase("error");
      return;
    }
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setPhase("uploading");
    setError(null);
    try {
      const response = await evaluateApproachFile(file, controller.signal);
      setResult(response);
      setPhase("success");
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") {
        setPhase("idle");
        return;
      }
      setError(reason instanceof Error ? reason : new Error("Evaluation failed."));
      setPhase("error");
    }
  }

  const issues = error instanceof ApiError ? error.fields : [];
  const rejections = result?.rejection_reasons ?? [];

  return (
    <main className="workspace evaluate-workspace">
      <header className="workspace-header">
        <div>
          <p className="eyebrow">Rules-first evaluation</p>
          <h1>Evaluate operational data</h1>
          <p className="workspace-subtitle sans">Upload observed ADS-B rows and receive the same approach-attempt evidence contract used by the loaded cohort.</p>
        </div>
        <div className="cohort-summary sans">
          <span>Evaluation engine</span>
          <b>{phase === "checking" ? "Checking capability…" : enabled ? "Available" : "Unavailable"}</b>
          <small>{health?.release_id ? `release ${health.release_id}` : "No model preparation required"}</small>
        </div>
      </header>

      <div className="evaluate-layout">
        <section className="upload-workspace" aria-labelledby="upload-title">
          <div className="section-heading sans">
            <div><p className="eyebrow">Input evidence</p><h2 id="upload-title">CSV or Parquet record</h2></div>
          </div>

          {phase === "checking" && <div className="loading-panel" aria-busy="true"><span className="sr-only">Checking upload capability</span></div>}

          {phase !== "checking" && !enabled && (
            <div className="state-panel" role="note">
              <h2>Evaluation is not enabled in this release</h2>
              <p>The loaded service can still be explored through its precomputed attempts.</p>
              <Link to="/">Open approach attempts</Link>
            </div>
          )}

          {phase !== "checking" && enabled && (
            <form className="upload-form sans" onSubmit={submit}>
              <label className="file-picker">
                <span>Choose operational record</span>
                <input
                  aria-label="Choose operational record"
                  type="file"
                  accept=".csv,.parquet,text/csv,application/vnd.apache.parquet"
                  onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
                />
                <b>{file ? file.name : "No file selected"}</b>
                <small>{file ? `${(file.size / 1024 / 1024).toFixed(2)} MB · retained if validation fails` : "Maximum size and row limits are enforced by the release."}</small>
              </label>
              <div className="upload-actions">
                <button type="submit" disabled={!file || phase === "uploading"}>{phase === "uploading" ? "Evaluating observed rows…" : "Evaluate approach attempts"}</button>
                {phase === "uploading" && <button type="button" className="secondary-button" onClick={() => controllerRef.current?.abort()}>Cancel</button>}
                <a href="/evaluation-synthetic-sample.csv" download>Download working example</a>
                <a href="/evaluation-template.csv" download>Download empty template</a>
              </div>
            </form>
          )}

          {phase === "error" && error && (
            <div className="validation-summary" role="alert" tabIndex={-1} ref={errorRef}>
              <h2>Evaluation could not complete</h2>
              <p>{error.message}</p>
              {issues.length > 0 && (
                <ul>{issues.map((issue, index) => <li key={`${issue.field}-${index}`}><a href={`#issue-${index}`}>{humanize(issue.field)}: {issue.message}</a></li>)}</ul>
              )}
              {issues.map((issue, index) => <p id={`issue-${index}`} key={`detail-${issue.field}-${index}`}><b>{humanize(issue.field)}</b> · {issue.message}</p>)}
              <button type="button" onClick={() => setPhase("idle")}>Review selected file</button>
            </div>
          )}

          {phase === "success" && result && (
            <section className="upload-results" aria-labelledby="results-title">
              <div className="section-heading sans">
                <div><p className="eyebrow">Evaluation complete</p><h2 id="results-title">{result.attempts.length} approach attempts</h2></div>
                <button className="secondary-button" onClick={() => downloadEvidence(result)}>Export evidence JSON</button>
              </div>
              <dl className="result-facts sans">
                <div><dt>Raw rows</dt><dd>{result.raw_rows?.toLocaleString() ?? "Unavailable"}</dd></div>
                <div><dt>Accepted rows</dt><dd>{result.accepted_rows?.toLocaleString() ?? "Unavailable"}</dd></div>
                <div><dt>Operations</dt><dd>{result.operation_count ?? "Unavailable"}</dd></div>
                <div><dt>Release</dt><dd className="mono">{result.release_id}</dd></div>
              </dl>

              {result.attempts.length === 0 ? (
                <div className="state-panel">
                  <h3>No approach attempts reached the gate</h3>
                  <p>The upload was parsed, but no record contained enough observed LEMD final-corridor evidence. Review rejection details or try a wider operational window.</p>
                </div>
              ) : (
                <ol className="upload-attempts">
                  {result.attempts.map((attempt) => (
                    <li key={attempt.attempt_id}>
                      <div className="upload-attempt-record">
                        <ApproachStatus status={attempt.status} compact />
                        <span><b className="mono">{attempt.runway ?? attempt.direction ?? "Unknown runway"}</b><small>{humanize(attempt.outcome)}</small></span>
                        <span><b>{attempt.failed_criteria.length ? attempt.failed_criteria.map(humanize).join(", ") : "No persistent crossing"}</b><small>{formatCoverage(attempt.coverage, attempt.observed_samples)}</small></span>
                        <time>{formatTime(attempt.start_time)}</time>
                      </div>
                      {!!attempt.criteria?.length && (
                        <details className="upload-evidence sans">
                          <summary>Inspect criterion evidence</summary>
                          {attempt.criteria.map((criterion) => (
                            <div key={criterion.name}>
                              <b>{humanize(criterion.name)}</b>
                              <span>{humanize(criterion.status)} · {criterion.observed_samples ?? 0} observed rows · {criterion.evidence.length} evidence spans</span>
                            </div>
                          ))}
                        </details>
                      )}
                    </li>
                  ))}
                </ol>
              )}

              {rejections.length > 0 && (
                <details className="upload-rejections sans">
                  <summary>{rejections.length} rejection reasons · partial evidence retained</summary>
                  <ul>{rejections.map((item, index) => <li key={`${item.code}-${index}`}><b>{humanize(item.code)}</b> · {item.message}{item.count ? ` · ${item.count.toLocaleString()} records` : ""}</li>)}</ul>
                </details>
              )}
            </section>
          )}
        </section>

        <aside className="context-rail upload-rail sans" aria-label="Upload requirements">
          <h2>Required schema</h2>
          <p>Columns required: <code>time</code>, <code>icao24</code>, <code>lat</code>, <code>lon</code>, <code>baroaltitude</code>, <code>velocity</code>, <code>heading</code>, <code>vertrate</code> and <code>onground</code>.</p>
          <p>Kinematic cells may be null when unobserved. Missing channels abstain instead of being invented.</p>
          <h2>Privacy and limits</h2>
          <p>Uploads are evaluated in memory for this request. The browser and server do not save the source file.</p>
          <h2>Assessment language</h2>
          <p>Results screen observable approach criteria. They are not emergency detections, safety certifications or causal findings.</p>
          <h2>Qualification</h2>
          <p>This research candidate missed its sealed assessability target, and independent review precision is unknown. Use results to inspect and label evidence, not for operational decisions.</p>
        </aside>
      </div>
    </main>
  );
}
