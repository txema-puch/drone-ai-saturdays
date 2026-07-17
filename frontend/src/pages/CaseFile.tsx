import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { getApproach, hasApiStatus, type ApproachDetail } from "../api";
import ApproachMap from "../components/ApproachMap";
import ApproachStatus from "../components/ApproachStatus";
import EvidenceTimeline from "../components/EvidenceTimeline";
import { formatCoverage, formatTime, humanize, shortDigest, STATUS_COPY } from "../lib/approach";

function renderValue(value: unknown): string {
  if (value == null) return "Unavailable";
  if (typeof value === "number") return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.length ? value.map(renderValue).join(", ") : "None";
  if (typeof value === "object") return Object.entries(value as Record<string, unknown>)
    .map(([key, nested]) => `${humanize(key)}: ${renderValue(nested)}`).join(" · ");
  return humanize(String(value));
}

function CriterionTable({ detail }: { detail: ApproachDetail }) {
  return (
    <div className="criterion-table sans">
      {detail.criteria.map((criterion) => (
        <article className={`criterion-row criterion-row--${criterion.status}`} key={criterion.name}>
          <div className="criterion-row__name">
            <h3>{humanize(criterion.name)}</h3>
            <span>{humanize(criterion.status)}</span>
          </div>
          <div>
            <span className="record-label">Observed evidence</span>
            <b>{criterion.observed_samples == null ? "Count unavailable" : `${criterion.observed_samples} rows`}</b>
          </div>
          <div className="criterion-row__evidence">
            <span className="record-label">Observed band / span</span>
            {criterion.evidence.length ? criterion.evidence.map((span, index) => (
              <p key={`${span.start_time}-${index}`}>
                {span.value != null ? `${span.value} ${span.unit ?? ""}` : "Limit crossing"}
                {span.limit != null ? ` · limit ${span.limit}` : ""}
                {` · ${formatTime(span.start_time)} to ${formatTime(span.end_time)}`}
              </p>
            )) : <p>{criterion.reason ? humanize(criterion.reason) : criterion.status === "within_limit" ? "No persistent limit crossing observed." : "Required evidence was not observed."}</p>}
          </div>
          <div>
            <span className="record-label">Provenance</span>
            <b>{humanize(criterion.reference_source ?? criterion.altitude_bias_source ?? "configured rule")}</b>
          </div>
        </article>
      ))}
    </div>
  );
}

export default function CaseFile() {
  const { attemptId = "" } = useParams();
  const [detail, setDetail] = useState<ApproachDetail | null>(null);
  const [error, setError] = useState<"missing" | "down" | null>(null);
  const [retry, setRetry] = useState(0);
  const [activeTime, setActiveTime] = useState<number | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setDetail(null);
    setError(null);
    getApproach(attemptId, controller.signal).then((result) => {
      setDetail(result);
      setActiveTime(result.start_time ?? result.path[0]?.time ?? 0);
    }).catch((reason: unknown) => {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setError(hasApiStatus(reason, 404) ? "missing" : "down");
    });
    return () => controller.abort();
  }, [attemptId, retry]);

  const activeIndex = useMemo(() => {
    if (!detail?.path.length || activeTime == null) return null;
    let best = 0;
    let distance = Number.POSITIVE_INFINITY;
    detail.path.forEach((point, index) => {
      const candidate = Math.abs((point.time ?? detail.start_time ?? 0) - activeTime);
      if (candidate < distance) {
        best = index;
        distance = candidate;
      }
    });
    return best;
  }, [activeTime, detail]);

  if (error) {
    return (
      <main className="workspace">
        <div className="state-panel state-panel--page" role={error === "down" ? "alert" : undefined}>
          <p className="eyebrow">Approach dossier</p>
          <h1>{error === "missing" ? "Attempt not found" : "Attempt evidence unavailable"}</h1>
          <p>{error === "missing" ? "This attempt is not present in the loaded release." : "The service could not return this dossier. Your queue filters are unchanged."}</p>
          <div className="state-actions">
            {error === "down" && <button onClick={() => setRetry((value) => value + 1)}>Retry dossier</button>}
            <Link to="/">Return to attempts</Link>
          </div>
        </div>
      </main>
    );
  }

  if (!detail) {
    return (
      <main className="workspace dossier-loading" aria-busy="true">
        <div className="loading-line loading-line--short" />
        <div className="loading-line loading-line--title" />
        <div className="loading-panel" />
      </main>
    );
  }

  const startTime = detail.start_time ?? detail.path[0]?.time ?? 0;
  const endTime = Math.max(startTime + 1, detail.end_time ?? detail.path[detail.path.length - 1]?.time ?? startTime + 1);
  const runway = detail.runway || detail.direction || "Unknown";
  const pairLevel = detail.runway_specificity === "direction";
  const activePoint = activeIndex == null ? null : detail.path[activeIndex];
  const provenance = {
    release_schema: detail.schema_version,
    engine: detail.engine_version,
    config_digest: detail.provenance?.config_sha256,
    reconstruction_policy: detail.provenance?.reconstruction_policy_sha256,
    geometry_digest: detail.geometry?.artifact_sha256,
    reference_digest: detail.reference?.artifact_sha256,
  };

  return (
    <main className="workspace dossier-workspace">
      <nav className="breadcrumb sans" aria-label="Breadcrumb">
        <Link to="/">Attempts</Link><span>/</span><span aria-current="page">{detail.attempt_id}</span>
      </nav>

      <header className="dossier-header">
        <div>
          <p className="eyebrow">Approach dossier · runway {runway}</p>
          <h1>{STATUS_COPY[detail.status].label}</h1>
          <p className="dossier-explanation sans">{STATUS_COPY[detail.status].explanation}</p>
        </div>
        <div className="dossier-status sans">
          <ApproachStatus status={detail.status} />
          <span className="mono">{detail.attempt_id}</span>
        </div>
      </header>

      <dl className="dossier-facts sans">
        <div><dt>Runway inference</dt><dd>{runway}{pairLevel ? " · pair-level" : ""}</dd></div>
        {pairLevel && <div><dt>Geometry anchor</dt><dd>{detail.geometry_runway ?? "Unavailable"} · provisional computation only</dd></div>}
        <div><dt>Outcome</dt><dd>{humanize(detail.outcome)}</dd></div>
        <div><dt>Coverage</dt><dd>{formatCoverage(detail.coverage, detail.observed_samples)}</dd></div>
        <div><dt>Observed interval</dt><dd>{formatTime(startTime)} – {formatTime(endTime)}</dd></div>
        <div><dt>Operation</dt><dd><Link to={`/approach-operations/${encodeURIComponent(detail.operation_ref)}`}>{detail.operation_ref}</Link></dd></div>
      </dl>

      {detail.status === "not_assessable" && (
        <div className="quality-notice sans" role="note">
          <b>Assessment withheld.</b> {(detail.reasons ?? []).length
            ? detail.reasons!.map(humanize).join(", ")
            : "The required evidence gate was not met."} No normal or abnormal verdict is inferred from missing evidence.
        </div>
      )}

      {pairLevel && (
        <div className="quality-notice sans" role="note">
          <b>Parallel runway unresolved.</b> The named geometry anchor is the lowest-scoring
          candidate used to calculate runway-relative proxies. It is not a claim that the
          aircraft used that exact runway.
        </div>
      )}

      <div className="dossier-layout">
        <div className="dossier-main">
          <section className="evidence-section" aria-labelledby="trajectory-title">
            <div className="section-heading sans">
              <div><p className="eyebrow">Synchronized evidence</p><h2 id="trajectory-title">Observed ground track and criterion timeline</h2></div>
              <span aria-live="polite">
                {activePoint ? `${formatTime(activePoint.time ?? activeTime)} · ${activePoint.along_track_m == null ? "position observed" : `${Math.round(activePoint.along_track_m / 100) / 10} km from threshold`}` : "No position selected"}
              </span>
            </div>
            {detail.path.length ? (
              <>
                <ApproachMap
                  path={detail.path}
                  activeIndex={activeIndex}
                  runway={runway}
                  outcome={detail.outcome}
                />
                <EvidenceTimeline
                  criteria={detail.criteria}
                  startTime={startTime}
                  endTime={endTime}
                  activeTime={activeTime ?? startTime}
                  runway={runway}
                  onTimeChange={setActiveTime}
                />
              </>
            ) : (
              <div className="state-panel"><h3>Observed positions unavailable</h3><p>Criterion rows remain available below.</p></div>
            )}
          </section>

          <section className="evidence-section" aria-labelledby="criteria-title">
            <div className="section-heading sans">
              <div><p className="eyebrow">Direct evidence</p><h2 id="criteria-title">Approach criteria</h2></div>
              <span>{detail.failed_criteria.length} persistent crossings</span>
            </div>
            <CriterionTable detail={detail} />
          </section>

          <details className="research-benchmark sans">
            <summary>Research benchmark <span>Does not determine this assessment</span></summary>
            {detail.research_benchmark ? (
              <div>
                <p><b>Historical LSTM comparison only.</b> Its segment score uses a different unit of analysis and cannot change this verdict or queue position.</p>
                <dl>
                  <div><dt>Model</dt><dd>{detail.research_benchmark.model_id ?? "Not identified"}</dd></div>
                  <div><dt>Segment</dt><dd>{detail.research_benchmark.segment_id ?? "Not covered"}</dd></div>
                  <div><dt>Score</dt><dd>{detail.research_benchmark.score ?? "Unavailable"}</dd></div>
                  <div><dt>Coverage</dt><dd>{renderValue(detail.research_benchmark.coverage)}</dd></div>
                </dl>
              </div>
            ) : <p>This release does not include a compatible research benchmark for the attempt.</p>}
          </details>
        </div>

        <aside className="context-rail dossier-rail sans" aria-label="Quality and provenance" tabIndex={0}>
          <h2>Quality gate</h2>
          {detail.quality ? Object.entries(detail.quality).map(([key, value]) => (
            <div className="rail-record" key={key}><span>{humanize(key)}</span><b>{renderValue(value)}</b></div>
          )) : <p>No quality detail was returned.</p>}
          {detail.context?.weather && (
            <>
              <h2>Weather context</h2>
              {[
                ["Observation", detail.context.weather.observed_at],
                ["QNH", detail.context.weather.qnh_hpa == null ? null : `${detail.context.weather.qnh_hpa} hPa`],
                ["Wind from", detail.context.weather.wind_from_direction_deg == null ? null : `${detail.context.weather.wind_from_direction_deg}°`],
                ["Wind speed", detail.context.weather.wind_speed_mps == null ? null : `${detail.context.weather.wind_speed_mps} m/s`],
                ["Headwind", detail.context.weather.headwind_mps == null ? null : `${Number(detail.context.weather.headwind_mps).toFixed(1)} m/s`],
                ["Crosswind from right", detail.context.weather.crosswind_from_right_mps == null ? null : `${Number(detail.context.weather.crosswind_from_right_mps).toFixed(1)} m/s`],
              ].map(([label, value]) => (
                <div className="rail-record" key={String(label)}><span>{String(label)}</span><b>{value == null ? "Unavailable" : String(value)}</b></div>
              ))}
              <p>Airport weather is the latest prior observation within the allowed age. QNH supplies a pressure-altitude proxy; wind does not create a verdict.</p>
            </>
          )}
          {detail.context?.aircraft && (
            <>
              <h2>Aircraft context</h2>
              <div className="rail-record"><span>Type</span><b className="mono">{renderValue(detail.context.aircraft.typecode)}</b></div>
              <div className="rail-record"><span>Model</span><b>{renderValue(detail.context.aircraft.model)}</b></div>
              <p>Registry metadata may not represent the aircraft at the historical operation date.</p>
            </>
          )}
          <h2>Missing context</h2>
          <p>{detail.context?.unavailable?.length
            ? `${detail.context.unavailable.map(humanize).join(", ")} remain unavailable.`
            : "Weather, QNH, mass, configuration and ATC intent are not inferred unless explicitly supplied by this release."}</p>
          <h2>Reproducibility</h2>
          {Object.entries(provenance).map(([key, value]) => (
            <div className="rail-record" key={key}><span>{humanize(key)}</span><b className="mono" title={typeof value === "string" ? value : undefined}>{shortDigest(value)}</b></div>
          ))}
        </aside>
      </div>
    </main>
  );
}
