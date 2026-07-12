import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { getFlight, type FlightDetail, type SimulationResult } from "../api";
import Attribution from "../components/Attribution";
import ReportPanel from "../components/ReportPanel";
import Stamp from "../components/Stamp";
import TemporalPanel from "../components/TemporalPanel";
import TrajectoryMap from "../components/TrajectoryMap";
import WhatIfPanel from "../components/WhatIfPanel";
import { CHANNELS, parseEpoch, pctColor, scoreColor } from "../lib/format";
import "./case.css";

export default function CaseFile() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<FlightDetail | null>(null);
  const [error, setError] = useState<"none" | "missing" | "down">("none");
  const [scrubIndex, setScrubIndex] = useState<number | null>(null);
  const [channel, setChannel] = useState<string>(CHANNELS[0].key);
  const [sim, setSim] = useState<SimulationResult | null>(null);

  const back = () => navigate("/");

  useEffect(() => {
    const ctrl = new AbortController();
    setDetail(null);
    setError("none");
    setScrubIndex(null);
    setSim(null);
    getFlight(Number(id), ctrl.signal)
      .then(setDetail)
      .catch((e) => {
        if (e?.name === "AbortError") return;
        setError(String(e?.message).includes("404") ? "missing" : "down");
      });
    return () => ctrl.abort();
  }, [id]);

  // Esc returns to the queue (DESIGN.md keyboard nav).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") back();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const meta = CHANNELS.find((c) => c.key === channel) ?? CHANNELS[0];
  const baseSeries = useMemo(() => (detail ? detail.channels[channel] ?? [] : []), [detail, channel]);

  if (error !== "none") {
    return (
      <div className="cf-state sans">
        <div className="big">{error === "missing" ? "No case file for this segment" : "Cannot reach the audit service"}</div>
        <p>
          {error === "missing"
            ? "This segment is in the docket but no detailed case file was baked for it. Open a flagged, typical, or held-aside case from the queue."
            : "The serve layer on :8077 is not responding."}
        </p>
        <button className="cf-back-btn sans" onClick={back}>
          ‹ Back to the audit queue
        </button>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="cf-state sans" aria-busy="true">
        <div className="big">Loading case file…</div>
      </div>
    );
  }

  const above = detail.window_score >= detail.threshold;
  const scrubVal = scrubIndex != null ? baseSeries[scrubIndex] : null;
  const scrubRE = scrubIndex != null ? detail.scores[scrubIndex] : null;
  const scrubAbove = scrubRE != null && scrubRE >= detail.step_threshold;

  const overlay = sim
    ? { series: sim.channels[channel] ?? [], scores: sim.scores, onsetIndex: sim.onset_index }
    : null;

  return (
    <div>
      <header className="cf-header">
        <div className="cf-crumb sans">
          <a href="/" onClick={(e) => { e.preventDefault(); back(); }}>
            ‹ Conformance Audit — LEMD
          </a>
          &nbsp;/&nbsp;
          <span>{detail.case_ref} · <a href={`/operation/${encodeURIComponent(detail.operation_ref)}`} onClick={(event) => { event.preventDefault(); navigate(`/operation/${encodeURIComponent(detail.operation_ref)}`); }}>{detail.operation_ref}</a> · {parseEpoch(detail.segment_id)}</span>
        </div>
        <div className="cf-titlerow">
          <div>
            <h1>
              Segment conformance review
              <span className="cf-sid mono">{detail.segment_id}</span>
            </h1>
            <Stamp label={detail.label} rotate style={{ marginTop: 8, display: "inline-block" }} />
          </div>
          <div className="cf-verdict">
            <div className="cf-score" style={{ color: scoreColor(detail.window_score) }}>
              {detail.window_score.toFixed(2)}
            </div>
            <div className="cf-pctband sans" style={{ color: pctColor(detail.pct) }}>
              {Math.round(detail.pct)}th percentile · {detail.band}
            </div>
            <div className="cf-vs sans">
              reconstruction error · threshold <b>{detail.threshold}</b> · {above ? "ABOVE" : "below"}
            </div>
            {sim && (
              <div className="cf-whatif-delta sans">
                what-if {sim.kind.replace(/_/g, " ")}:{" "}
                <b style={{ color: scoreColor(detail.window_score) }}>{detail.window_score.toFixed(2)}</b> →{" "}
                <b style={{ color: scoreColor(sim.window_score) }}>{sim.window_score.toFixed(2)}</b>{" "}
                ({Math.round(sim.pct)}th · {sim.anomalous ? "flagged" : "below thr"})
              </div>
            )}
          </div>
        </div>
      </header>

      <section className="cf-operation sans" aria-labelledby="operation-context-title">
        <div>
          <h2 id="operation-context-title"><a href={`/operation/${encodeURIComponent(detail.operation_ref)}`} onClick={(event) => { event.preventDefault(); navigate(`/operation/${encodeURIComponent(detail.operation_ref)}`); }}>Operation context · {detail.operation_ref}</a></h2>
          <p>{detail.operation_segments.length} scored {detail.operation_segments.length === 1 ? "segment" : "segments"}. Each score remains independent.</p>
        </div>
        <div className="cf-neighbors" aria-label="Segments in this operation">
          {detail.operation_segments.map((segment) => {
            const current = segment.id === detail.id;
            const segmentNumber = segment.segment_id.split("#")[1] ?? segment.segment_id;
            const content = <><b>{segment.case_ref}</b><span>{segmentNumber} · RE {segment.score.toFixed(2)} · {segment.label.replace("_", "-")}</span></>;
            return segment.has_case && !current ? (
              <button key={segment.id} onClick={() => navigate(`/case/${segment.id}`)}>{content}</button>
            ) : (
              <div key={segment.id} className={current ? "current" : ""} aria-current={current ? "page" : undefined}>{content}</div>
            );
          })}
        </div>
      </section>

      <section className="cf-assessment sans" aria-label="Segment assessment">
        <div><span>Model status</span><b>{detail.anomalous ? "Flagged" : "Below threshold"}</b></div>
        <div><span>Data-quality status</span><b>{detail.assessment_state.replace(/_/g, " ")}</b></div>
        <div><span>Behavioral verdict</span><b>{detail.behavioral_verdict.replace(/_/g, " ")}</b></div>
      </section>

      {detail.behavioral_verdict === "not_assessable" && (
        <div className="cf-trunc sans" role="note">
          {detail.assessment_state === "data_quality_conflict" ? (
            <>
              <b>Data-quality conflict.</b> The scored timeline contains a physically inconsistent
              transition: maximum altitude jump {Math.round(detail.max_altitude_jump_m).toLocaleString()} m,
              implied vertical rate {detail.max_implied_vertical_rate_mps.toFixed(1)} m/s, and implied
              ground speed {detail.max_implied_ground_speed_mps.toFixed(1)} m/s. The raw model score is
              retained, but behavioral conformance is <b>not assessable</b>. The system does not assign
              a sensor, ingestion, spoofing, or behavioral cause.
            </>
          ) : detail.assessment_state === "insufficient_data" ? (
            <>
              <b>Insufficient observed data.</b> Only {detail.valid_steps} timesteps contribute to the
              reconstruction error ({Math.round(detail.observed_fraction * 100)}% observed coverage).
              A low or high raw score is not reliable behavioral evidence. Analyst review of source
              telemetry is required.
            </>
          ) : detail.truncated ? (
            <>
              <b>Window truncated.</b> This segment is {detail.n_steps} steps (~
              {Math.round((detail.n_steps * detail.step_seconds) / 60)} min); the model scores only
              the first {detail.valid_steps} (T=260, ~43 min). For a long arrival the terminal
              approach is beyond the window and is <b>not scored</b> — this evidence is the earlier
              cruise/descent phase.
            </>
          ) : (
            <>
              <b>Terminal coverage absent.</b> Within the scored window this segment never gets
              both low and close to a LEMD runway. This may reflect traffic context, coverage,
              phase classification, or another data limitation. The system does not assign a
              cause, and the raw score is not reliable evidence of behavioral non-conformance.
            </>
          )}{" "}
              Known deployment limitation (D-014); raw model output retained.
        </div>
      )}

      <div className="cf-grid">
        <div className="card cf-mapwrap">
          <h2>
            Trajectory · actual vs reconstruction
            <span className="ro">{scrubAbove ? "⚠ above step threshold" : ""}</span>
          </h2>
          <div className="cf-legend sans">
            actual <i style={{ background: "var(--actual)" }} />
            <br />
            reconstruction <i style={{ background: "var(--blue)" }} />
            <br />
            deviation <i style={{ background: "var(--amber)" }} />
            {detail.n_siblings > 1 && (
              <>
                <br />
                rest of operation <i style={{ background: "var(--chart-context)" }} />
              </>
            )}
            {sim && (
              <>
                <br />
                what-if <i style={{ background: "var(--inject)" }} />
              </>
            )}
          </div>
          <TrajectoryMap
            path={detail.path}
            reconstructed={detail.reconstructed}
            center={detail.center}
            stepScores={detail.scores}
            stepThreshold={detail.step_threshold}
            scrubIndex={scrubIndex}
            overlayPath={sim?.path ?? null}
            contextPath={detail.context_path}
          />
        </div>

        <div className="card">
          <h2>Per-feature attribution · what drove the score</h2>
          <Attribution attribution={detail.feature_attribution} />
          <p className="cf-note sans">
            Diagnostic only — per-feature reconstruction error, never a tuning knob. The dominant
            channels are the signature of how this segment diverged from learned-normal behaviour.
          </p>
          <ReportPanel report={detail.report} model={detail.report_model} />
        </div>

        <div className="card cf-full">
          <h2>
            Temporal analysis · {meta.label.toLowerCase()} + reconstruction error · hover or arrow-key to scrub
            <span className="ro">
              {scrubIndex != null
                ? `step ${scrubIndex} · ${meta.label.toLowerCase()} ${Math.round(scrubVal ?? 0)} ${meta.unit} · RE ${(scrubRE ?? 0).toFixed(2)}`
                : ""}
            </span>
          </h2>
          <div className="cf-channels sans" role="group" aria-label="Temporal channel">
            {CHANNELS.map((c) => (
              <button
                key={c.key}
                className={`cf-chan${channel === c.key ? " on" : ""}`}
                aria-pressed={channel === c.key}
                onClick={() => setChannel(c.key)}
              >
                {c.label}
              </button>
            ))}
          </div>
          <TemporalPanel
            series={baseSeries}
            seriesLabel={`${meta.label.toUpperCase()} (${meta.unit})`}
            scores={detail.scores}
            stepThreshold={detail.step_threshold}
            scrubIndex={scrubIndex}
            onScrub={setScrubIndex}
            overlay={overlay}
          />
        </div>

        <div className="card">
          <h2>Analyst what-if · perturb &amp; re-score (sandbox)</h2>
          <WhatIfPanel
            flightId={detail.id}
            active={sim != null}
            onResult={setSim}
            onClear={() => setSim(null)}
          />
        </div>
      </div>

      <div className="cf-foot sans">
        {detail.case_ref} · segment {detail.segment_id} · {detail.valid_steps} valid steps · scrub the lower charts to trace
        where this segment diverged
      </div>
    </div>
  );
}
