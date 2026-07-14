import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import {
  ApiError,
  evaluateFile,
  getHealth,
  prepareModel,
  type EvaluationResponse,
  type EvaluationResult,
  type Health,
} from "../api";
import Attribution from "../components/Attribution";
import TemporalPanel from "../components/TemporalPanel";
import TrajectoryMap from "../components/TrajectoryMap";
import { CHANNELS, pctColor, scoreColor } from "../lib/format";
import "./evaluate.css";

type UploadPhase = "idle" | "reading" | "evaluating" | "busy" | "error" | "done";

interface UploadState {
  phase: UploadPhase;
  file: File | null;
  error: ApiError | null;
  response: EvaluationResponse | null;
}

const EMPTY_UPLOAD: UploadState = { phase: "idle", file: null, error: null, response: null };

function useDesktopWorkspace() {
  const query = "(min-width: 1024px)";
  const [desktop, setDesktop] = useState(() =>
    typeof window.matchMedia === "function" ? window.matchMedia(query).matches : true,
  );
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(query);
    const onChange = () => setDesktop(media.matches);
    onChange();
    media.addEventListener?.("change", onChange);
    return () => media.removeEventListener?.("change", onChange);
  }, []);
  return desktop;
}

function assessmentCopy(result: EvaluationResult) {
  if (result.assessment_state === "insufficient_data") {
    return `Only ${result.valid_steps} observed timesteps contribute to the score (${Math.round(result.observed_fraction * 100)}% coverage). Behavioral conformance is not assessable.`;
  }
  if (result.assessment_state === "data_quality_conflict") {
    return `Telemetry contains a physically inconsistent transition (maximum implied vertical rate ${result.max_implied_vertical_rate_mps.toFixed(1)} m/s; ground speed ${result.max_implied_ground_speed_mps.toFixed(1)} m/s). Cause is unassigned and behavioral conformance is not assessable.`;
  }
  if (result.assessment_state === "coverage_limited") {
    return "The scored window lacks a low-and-close LEMD terminal phase. Behavioral conformance is not assessable.";
  }
  return "No deployment data-quality conflict was detected. Model evidence is available for analyst review.";
}

function exportResponse(response: EvaluationResponse) {
  const blob = new Blob([JSON.stringify(response, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `sadar-evaluation-${response.dataset_digest.slice(0, 12)}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function Evaluate() {
  const desktop = useDesktopWorkspace();
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [prepareError, setPrepareError] = useState(false);
  const [upload, setUpload] = useState<UploadState>(EMPTY_UPLOAD);
  const [selectedRef, setSelectedRef] = useState("");
  const [scrubIndex, setScrubIndex] = useState<number | null>(null);
  const [channel, setChannel] = useState("baroaltitude");
  const inputRef = useRef<HTMLInputElement>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const requestRef = useRef<AbortController | null>(null);
  const requestGeneration = useRef(0);

  const refreshHealth = useCallback(async (signal?: AbortSignal) => {
    try {
      const value = await getHealth(signal);
      setHealth(value);
      setHealthError(false);
      return value;
    } catch (error) {
      if ((error as { name?: string })?.name !== "AbortError") setHealthError(true);
      return null;
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refreshHealth(controller.signal);
    return () => controller.abort();
  }, [refreshHealth]);

  useEffect(() => {
    if (health?.model_state !== "loading") return;
    const controller = new AbortController();
    const timer = window.setInterval(() => void refreshHealth(controller.signal), 1000);
    return () => {
      window.clearInterval(timer);
      controller.abort();
    };
  }, [health?.model_state, refreshHealth]);

  useEffect(() => {
    if (upload.phase === "error" || upload.phase === "busy") errorRef.current?.focus();
  }, [upload.phase]);

  useEffect(() => () => {
    requestGeneration.current += 1;
    requestRef.current?.abort();
  }, []);

  const clear = useCallback((abort = true) => {
    requestGeneration.current += 1;
    if (abort) requestRef.current?.abort();
    requestRef.current = null;
    setUpload(EMPTY_UPLOAD);
    setSelectedRef("");
    setScrubIndex(null);
    setChannel("baroaltitude");
    if (inputRef.current) inputRef.current.value = "";
  }, []);

  const submit = useCallback(async (file: File) => {
    requestGeneration.current += 1;
    const generation = requestGeneration.current;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setSelectedRef("");
    setScrubIndex(null);
    setUpload({ phase: "reading", file, error: null, response: null });

    await Promise.resolve();
    if (generation !== requestGeneration.current) return;
    setUpload({ phase: "evaluating", file, error: null, response: null });
    try {
      const response = await evaluateFile(file, controller.signal);
      if (generation !== requestGeneration.current) return;
      requestRef.current = null;
      setUpload({ phase: "done", file, error: null, response });
      setSelectedRef(response.results[0]?.evaluation_ref ?? "");
    } catch (error) {
      if (generation !== requestGeneration.current || (error as { name?: string })?.name === "AbortError") return;
      requestRef.current = null;
      const apiError = error instanceof ApiError
        ? error
        : new ApiError(0, "network_error", "The evaluation service could not be reached.");
      setUpload({
        phase: apiError.status === 429 ? "busy" : "error",
        file,
        error: apiError,
        response: null,
      });
      if (apiError.status === 503) void refreshHealth();
    }
  }, [refreshHealth]);

  const selected = useMemo(
    () => upload.response?.results.find((result) => result.evaluation_ref === selectedRef) ?? null,
    [upload.response, selectedRef],
  );
  const channelOptions = useMemo(() => {
    if (!selected) return [];
    const known = CHANNELS.filter((item) => selected.channels[item.key]?.length);
    return known.length ? known : Object.keys(selected.channels).map((key) => ({ key, label: key, unit: "" }));
  }, [selected]);
  const activeChannel = channelOptions.find((item) => item.key === channel) ?? channelOptions[0];
  const series = selected && activeChannel ? selected.channels[activeChannel.key] ?? [] : [];

  async function onPrepare() {
    setPreparing(true);
    setPrepareError(false);
    try {
      const state = await prepareModel();
      setHealth((current) => current ? { ...current, ...state } : current);
      await refreshHealth();
    } catch {
      setPrepareError(true);
      await refreshHealth();
    } finally {
      setPreparing(false);
    }
  }

  function choose(files: FileList | null) {
    const file = files?.[0];
    if (file) void submit(file);
  }

  const statusText = upload.phase === "reading"
    ? "Reading file…"
    : upload.phase === "evaluating"
      ? "Uploading and evaluating…"
      : upload.phase === "busy"
        ? "Analysis is busy"
        : upload.phase === "done"
          ? "Evaluation complete"
          : "";

  if (healthError && !health) {
    return <main className="ev-state sans"><h1>Cannot reach the audit service</h1><p>Evaluation capability could not be checked.</p><button onClick={() => void refreshHealth()}>Retry</button></main>;
  }
  if (!health) {
    return <main className="ev-state sans" aria-busy="true"><h1>Checking evaluation capability…</h1></main>;
  }
  if (health.evaluation_enabled !== true) {
    return <main className="ev-state sans"><h1>Evaluation is not enabled</h1><p>This deployment is a read-only retrospective audit. No upload endpoint is available.</p><Link to="/">Return to the audit queue</Link></main>;
  }

  return (
    <main className="ev-page">
      <header className="ev-header">
        <div>
          <p className="microlabel">Post-hoc trajectory evidence</p>
          <h1>Evaluate new data</h1>
          <p className="ev-sub sans">Score a bounded OpenSky-style observation file with the frozen release model.</p>
        </div>
        <dl className="ev-identity sans">
          <div><dt>Release</dt><dd className="mono">{health.release_id ?? "current"}</dd></div>
          <div><dt>Model</dt><dd className="mono">{health.model_id ?? "frozen LSTM AE"}</dd></div>
          <div><dt>Status</dt><dd>{(health.model_state ?? "not_loaded").replace("_", " ")}</dd></div>
        </dl>
      </header>

      <section className="ev-privacy sans" role="note">
        <b>Public anonymous demo.</b> The application keeps no upload history, but its host may
        snapshot runtime memory while the Machine is suspended. Do not upload confidential or
        proprietary data.
      </section>

      {!desktop ? (
        <section className="ev-desktop sans">
          <h2>Desktop workspace required</h2>
          <p>The forensic evidence workspace requires a viewport at least 1024 px wide. Upload is disabled here.</p>
          <Link to="/">Return to the audit queue</Link>
        </section>
      ) : (
        <>
          {(health.model_state ?? "not_loaded") !== "ready" ? (
            <section className="ev-prepare card sans" aria-live="polite">
              {(health.model_state ?? "not_loaded") === "not_loaded" && <><h2>Frozen model not prepared</h2><p>Load the immutable release model before selecting a file.</p><button onClick={() => void onPrepare()} disabled={preparing}>{preparing ? "Starting…" : "Prepare model"}</button></>}
              {health.model_state === "loading" && <><h2>Preparing frozen model…</h2><p className="ev-working">Loading is indeterminate. You may continue browsing the audit queue.</p><Link to="/">Open audit queue</Link></>}
              {health.model_state === "failed" && <><h2>Model preparation failed</h2><p>The audit dossier remains available. {health.model_retry_remaining ? "One bounded retry remains." : "No automatic retry remains."}</p>{Boolean(health.model_retry_remaining) && <button onClick={() => void onPrepare()} disabled={preparing}>Retry preparation</button>} <Link to="/">Return to audit queue</Link></>}
              {prepareError && <p role="alert">The model preparation request could not be completed. The audit dossier remains available; retry when the service is reachable.</p>}
            </section>
          ) : (
            <>
              <section className="ev-action card sans" aria-labelledby="upload-title">
                <div className="ev-upload-copy">
                  <h2 id="upload-title">Select observation file</h2>
                  <p>Flat UTF-8 CSV or Parquet · 10 MiB · 50,000 raw rows · 100,000 resampled rows · 25 accepted segments.</p>
                  <p>Epoch seconds and SI units. Required: <span className="mono">time, icao24, lat, lon, baroaltitude, velocity, heading, vertrate, onground</span>.</p>
                  <p>Measured channels may be null; structural fields may not. <span className="mono">onground</span> accepts true/false, 0/1, or null.</p>
                  <details className="ev-schema">
                    <summary>Schema and unit details</summary>
                    <p><span className="mono">time</span>: epoch-second integer; latitude/longitude and heading: degrees; altitude: metres; velocity and vertical rate: m/s.</p>
                    <p>Optional: <span className="mono">callsign, squawk, geoaltitude, alert, spi, lastcontact</span>. Derived identifiers and phase/distance fields are ignored and recomputed.</p>
                    <p>One flat comma-delimited header for CSV, no duplicate columns, finite values only, and trajectories engaging the LEMD analysis boundary.</p>
                  </details>
                  <div className="ev-downloads"><a href="/evaluation-template.csv" download>Download schema template</a><a href="/evaluation-synthetic-sample.csv" download>Download synthetic sample</a></div>
                </div>
                <div
                  className={`ev-drop${upload.phase === "reading" || upload.phase === "evaluating" ? " is-busy" : ""}`}
                  onDragOver={(event) => event.preventDefault()}
                  onDrop={(event) => { event.preventDefault(); choose(event.dataTransfer.files); }}
                >
                  <label htmlFor="evaluation-file">Select or drop CSV/Parquet</label>
                  <input ref={inputRef} id="evaluation-file" type="file" accept=".csv,.parquet,text/csv,application/vnd.apache.parquet" onChange={(event) => choose(event.target.files)} disabled={upload.phase === "reading" || upload.phase === "evaluating"} />
                  {upload.file && <span className="mono ev-filename">{upload.file.name}</span>}
                </div>
                {(upload.phase === "reading" || upload.phase === "evaluating") && <button className="ev-cancel" onClick={() => clear(true)}>Cancel</button>}
                {upload.file && !["reading", "evaluating"].includes(upload.phase) && <button className="ev-replace" onClick={() => { if (inputRef.current) { inputRef.current.value = ""; inputRef.current.click(); } }}>Replace file</button>}
              </section>

              <div className="sr-only" aria-live="polite">{statusText}</div>
              {(upload.phase === "reading" || upload.phase === "evaluating") && <section className="ev-progress sans" aria-busy="true"><b>{statusText}</b><span>No percentage is estimated. Cancel hides late results; server work may already be running.</span></section>}

              {(upload.phase === "error" || upload.phase === "busy") && upload.error && (
                <section ref={errorRef} tabIndex={-1} className="ev-error sans" role="alert">
                  <h2>{upload.error.status === 408 ? "Upload timed out" : upload.phase === "busy" ? "Analysis is busy" : "File could not be evaluated"}</h2>
                  <p>{upload.error.message}</p>
                  {upload.error.fields.length > 0 && <ul>{upload.error.fields.map((issue, index) => <li key={`${issue.field}-${index}`}><b>{issue.field}</b>: {issue.message}</li>)}</ul>}
                  {upload.error.retryAfter != null && <p>Retry after approximately {upload.error.retryAfter} seconds.</p>}
                  {upload.file && <button onClick={() => void submit(upload.file!)}>Retry file</button>}
                </section>
              )}

              {upload.phase === "done" && upload.response && (
                <section className="ev-results" aria-label="Evaluation results">
                  <aside className="ev-rail sans">
                    <div>
                      <h2>Dataset summary</h2>
                      <dl className="ev-counts">
                        <div><dt>Raw rows</dt><dd>{upload.response.raw_rows.toLocaleString()}</dd></div>
                        <div><dt>Derived rows</dt><dd>{upload.response.derived_rows.toLocaleString()}</dd></div>
                        <div><dt>Accepted rows</dt><dd>{upload.response.accepted_rows.toLocaleString()}</dd></div>
                        <div><dt>Accepted segments</dt><dd>{upload.response.accepted_segments}</dd></div>
                        <div><dt>Rejected segments</dt><dd>{upload.response.rejected_segments}</dd></div>
                        <div><dt>Duplicates collapsed</dt><dd>{upload.response.duplicate_rows_collapsed}</dd></div>
                      </dl>
                      {upload.response.rejection_reasons.length > 0 && <div className="ev-rejections"><h3>Bounded rejection reasons</h3><ul>{upload.response.rejection_reasons.map((reason) => <li key={reason.code}>{reason.message} <b>×{reason.count}</b></li>)}</ul></div>}
                    </div>
                    {upload.response.results.length > 0 && <label className="ev-selector">Accepted segment<select value={selectedRef} onChange={(event) => { setSelectedRef(event.target.value); setScrubIndex(null); }} aria-label="Accepted segment">{upload.response.results.map((result) => <option key={result.evaluation_ref} value={result.evaluation_ref}>{result.segment_id}</option>)}</select></label>}
                    <div className="ev-actions"><button onClick={() => exportResponse(upload.response!)}>Export JSON</button><button className="ev-clear" onClick={() => clear(false)}>Clear</button></div>
                    <p className="ev-digest mono">dataset {upload.response.dataset_digest.slice(0, 16)}…</p>
                  </aside>

                  {selected ? (
                    <article className="ev-evidence" aria-labelledby="segment-evidence-title">
                      <header className="ev-segment-head sans">
                        <div><p className="microlabel">Segment evidence</p><h2 id="segment-evidence-title" className="mono">{selected.segment_id}</h2></div>
                        <span className="ev-ref mono">{selected.evaluation_ref}</span>
                      </header>

                      <section className={`ev-quality ev-quality--${selected.review_lane} sans`}>
                        <div><h3>Assessability and data quality</h3><strong>{selected.assessment_state.replace(/_/g, " ")}</strong></div>
                        <p>{assessmentCopy(selected)}</p>
                        {selected.data_quality_flags.length > 0 && <p className="mono">Flags: {selected.data_quality_flags.join(", ")}</p>}
                      </section>

                      <section className="ev-model sans" aria-label="Model evidence">
                        <div><span>Model status</span><b>{selected.model_status.replace("_", " ")}</b></div>
                        <div><span>Reconstruction error</span><b style={{ color: scoreColor(selected.window_score, selected.threshold) }}>{selected.window_score.toFixed(3)}</b></div>
                        <div><span>Frozen-cohort percentile</span><b style={{ color: pctColor(selected.pct) }}>{selected.pct.toFixed(1)}</b></div>
                        <p>The percentile is relative to the frozen release cohort, not this uploaded file. This is model evidence, not a safety or operational verdict.</p>
                      </section>

                      <div className="ev-evidence-grid">
                        <section className="card ev-map"><h2>Trajectory · measured vs reconstruction</h2><TrajectoryMap path={selected.path} reconstructed={selected.reconstructed} center={selected.center} stepScores={selected.scores} stepThreshold={selected.step_threshold} scrubIndex={scrubIndex} /></section>
                        <section className="card"><h2>Per-feature attribution</h2><Attribution attribution={selected.feature_attribution} /><p className="ev-note sans">Diagnostic reconstruction error only. No generated narrative for uploaded data.</p></section>
                        <section className="card ev-temporal"><h2>Temporal evidence · {activeChannel?.label.toLowerCase() ?? "channel"} + reconstruction error</h2><div className="ev-channels sans" role="group" aria-label="Temporal channel">{channelOptions.map((item) => <button key={item.key} aria-pressed={activeChannel?.key === item.key} className={activeChannel?.key === item.key ? "on" : ""} onClick={() => setChannel(item.key)}>{item.label}</button>)}</div><TemporalPanel series={series} seriesLabel={`${activeChannel?.label.toUpperCase() ?? "CHANNEL"}${activeChannel?.unit ? ` (${activeChannel.unit})` : ""}`} scores={selected.scores} stepThreshold={selected.step_threshold} scrubIndex={scrubIndex} onScrub={setScrubIndex} /></section>
                      </div>
                    </article>
                  ) : (
                    <div className="ev-zero sans"><h2>No assessable LEMD-engaging segments</h2><p>The file was processed, but no segment met the frozen derivation and preprocessing contract. Review the schema and limits or choose another file.</p></div>
                  )}
                </section>
              )}
            </>
          )}
        </>
      )}
    </main>
  );
}
