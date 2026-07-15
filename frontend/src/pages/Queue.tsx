import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import {
  getApproaches,
  getHealth,
  type ApproachFilters,
  type ApproachStatus as ApproachStatusValue,
  type ApproachSummary,
  type Health,
} from "../api";
import ApproachStatus from "../components/ApproachStatus";
import { formatCoverage, formatTime, humanize, STATUS_ORDER } from "../lib/approach";

const FILTERS = ["status", "direction", "criterion", "outcome", "quality"] as const;
type FilterName = typeof FILTERS[number];

const STATUS_OPTIONS: ApproachStatusValue[] = [
  "review_required",
  "partial_observation",
  "criteria_observed",
  "not_assessable",
];

function AttemptRow({ attempt }: { attempt: ApproachSummary }) {
  const failed = attempt.failed_criteria ?? [];
  const runway = attempt.runway || attempt.direction || "Unknown";
  return (
    <li className={`attempt-record attempt-record--${attempt.status}`}>
      <Link
        className="attempt-record__link"
        to={`/approaches/${encodeURIComponent(attempt.attempt_id)}`}
        aria-label={`Open approach attempt ${attempt.attempt_id}: ${humanize(attempt.status)}, runway ${runway}`}
      >
        <span className="attempt-record__cell attempt-record__status" data-label="Status">
          <ApproachStatus status={attempt.status} compact />
          <small className="mono">{attempt.attempt_id}</small>
        </span>
        <span className="attempt-record__cell" data-label="Runway">
          <b className="mono">{runway}</b>
          <small>{humanize(attempt.outcome)}</small>
        </span>
        <span className="attempt-record__cell attempt-record__evidence" data-label="Failed criteria">
          <b>{failed.length ? failed.map(humanize).join(", ") : "No persistent crossing"}</b>
          <small>{attempt.reasons?.length ? attempt.reasons.map(humanize).join(", ") : "Evidence gate complete"}</small>
        </span>
        <span className="attempt-record__cell" data-label="Coverage">
          <b>{formatCoverage(attempt.coverage, attempt.observed_samples)}</b>
          <small>{attempt.quality_flags?.length ? `${attempt.quality_flags.length} quality flags` : "No fatal quality flag"}</small>
        </span>
        <span className="attempt-record__cell" data-label="Time">
          <b>{formatTime(attempt.start_time)}</b>
          <small className="mono">{attempt.operation_ref}</small>
        </span>
      </Link>
    </li>
  );
}

export default function Queue() {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.toString();
  const [attempts, setAttempts] = useState<ApproachSummary[] | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);

  const filters = useMemo<ApproachFilters>(() => ({
    limit: 500,
    status: searchParams.get("status") ?? undefined,
    direction: searchParams.get("direction") ?? undefined,
    criterion: searchParams.get("criterion") ?? undefined,
    outcome: searchParams.get("outcome") ?? undefined,
    quality: searchParams.get("quality") ?? undefined,
  }), [query]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const controller = new AbortController();
    setAttempts(null);
    setError(null);
    Promise.all([
      getApproaches(filters, controller.signal),
      getHealth(controller.signal).catch(() => null),
    ]).then(([items, healthResult]) => {
      setAttempts(items);
      setHealth(healthResult);
    }).catch((reason: unknown) => {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setError(reason instanceof Error ? reason.message : "The approach service did not respond.");
    });
    return () => controller.abort();
  }, [filters, retry]);

  const visibleAttempts = useMemo(() => {
    const quality = filters.quality;
    const filtered = !quality || quality === "all"
      ? attempts ?? []
      : (attempts ?? []).filter((attempt) => {
          const flags = attempt.quality_flags ?? attempt.reasons ?? [];
          return quality === "limited" ? flags.length > 0 : flags.length === 0;
        });
    return [...filtered].sort((a, b) => {
      const status = STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status);
      if (status) return status;
      const failures = (b.failed_criteria?.length ?? 0) - (a.failed_criteria?.length ?? 0);
      return failures || (b.start_time ?? 0) - (a.start_time ?? 0);
    });
  }, [attempts, filters.quality]);

  function setFilter(name: FilterName, value: string) {
    const next = new URLSearchParams(searchParams);
    if (!value || value === "all") next.delete(name);
    else next.set(name, value);
    setSearchParams(next, { replace: true });
  }

  function clearFilters() {
    setSearchParams({}, { replace: true });
  }

  const hasFilters = FILTERS.some((name) => searchParams.has(name));
  const statusCounts = health?.status_counts ?? {};

  return (
    <main className="workspace queue-workspace">
      <header className="workspace-header">
        <div>
          <p className="eyebrow">LEMD · post-flight screening</p>
          <h1>Approach attempts</h1>
          <p className="workspace-subtitle sans">
            Screens ADS-B-observable approach criteria. It does not detect emergencies or certify operational safety.
          </p>
        </div>
        <div className="cohort-summary sans" aria-label="Loaded cohort">
          <span>Loaded cohort</span>
          <b>{health?.attempts ?? attempts?.length ?? "—"} attempts</b>
          <small>{health?.release_id ? `release ${health.release_id}` : "Release metadata unavailable"}</small>
        </div>
      </header>

      <div className="queue-layout">
        <section className="queue-main" aria-labelledby="attempt-list-title">
          <form className="attempt-filters sans" aria-label="Filter approach attempts" onSubmit={(event) => event.preventDefault()}>
            <label>Status
              <select value={filters.status ?? "all"} onChange={(event) => setFilter("status", event.target.value)}>
                <option value="all">All statuses</option>
                {STATUS_OPTIONS.map((status) => <option key={status} value={status}>{humanize(status)}</option>)}
              </select>
            </label>
            <label>Direction
              <select value={filters.direction ?? "all"} onChange={(event) => setFilter("direction", event.target.value)}>
                <option value="all">All directions</option>
                <option value="18">18 arrivals</option>
                <option value="32">32 arrivals</option>
              </select>
            </label>
            <label>Criterion
              <select value={filters.criterion ?? "all"} onChange={(event) => setFilter("criterion", event.target.value)}>
                <option value="all">All criteria</option>
                <option value="lateral_path_proxy">Lateral path</option>
                <option value="barometric_path_proxy">Barometric path</option>
                <option value="observed_descent_rate">Descent rate</option>
                <option value="observed_ground_speed_envelope">Ground speed</option>
                <option value="late_track_correction">Late track correction</option>
              </select>
            </label>
            <label>Outcome
              <select value={filters.outcome ?? "all"} onChange={(event) => setFilter("outcome", event.target.value)}>
                <option value="all">All outcomes</option>
                <option value="landing_observed">Landing observed</option>
                <option value="go_around">Go-around pattern</option>
                <option value="final_gate_observed">Final gate observed</option>
                <option value="incomplete">Incomplete record</option>
              </select>
            </label>
            <label>Quality
              <select value={filters.quality ?? "all"} onChange={(event) => setFilter("quality", event.target.value)}>
                <option value="all">All quality states</option>
                <option value="complete">No fatal flag</option>
                <option value="limited">Quality limited</option>
              </select>
            </label>
            {hasFilters && <button className="text-button" type="button" onClick={clearFilters}>Clear filters</button>}
          </form>

          <div className="attempt-list-header sans">
            <h2 id="attempt-list-title">{attempts ? `${visibleAttempts.length.toLocaleString()} attempts` : "Loading attempts"}</h2>
            <span>Prioritized by status, failed criteria, then time</span>
          </div>

          {error && (
            <div className="state-panel" role="alert">
              <h2>Attempt list unavailable</h2>
              <p>{error}</p>
              <button type="button" onClick={() => setRetry((value) => value + 1)}>Retry with these filters</button>
            </div>
          )}

          {!error && attempts === null && (
            <div className="attempt-skeleton" aria-busy="true" aria-label="Loading approach attempts">
              {Array.from({ length: 6 }, (_, index) => <span key={index} />)}
            </div>
          )}

          {!error && attempts !== null && visibleAttempts.length === 0 && (
            <div className="state-panel">
              <h2>No attempts match this view</h2>
              <p>The cohort loaded successfully. Remove a filter to return to assessable evidence.</p>
              <button type="button" onClick={clearFilters}>Clear all filters</button>
            </div>
          )}

          {!error && visibleAttempts.length > 0 && (
            <>
              <div className="attempt-columns sans" aria-hidden="true">
                <span>Status / attempt</span><span>Runway / outcome</span><span>Failed criteria</span><span>Coverage</span><span>Time / operation</span>
              </div>
              <ol className="attempt-list">
                {visibleAttempts.map((attempt) => <AttemptRow attempt={attempt} key={attempt.attempt_id} />)}
              </ol>
            </>
          )}
        </section>

        <aside className="context-rail sans" aria-label="Cohort status summary">
          <h2>Status scope</h2>
          {STATUS_OPTIONS.map((status) => (
            <button key={status} onClick={() => setFilter("status", status)} aria-pressed={filters.status === status}>
              <ApproachStatus status={status} compact />
              <b>{statusCounts[status] ?? (attempts ?? []).filter((item) => item.status === status).length}</b>
            </button>
          ))}
          <div className="context-rail__note">
            <b>How to read this queue</b>
            <p>Review status comes from observed rule evidence. Missing coverage stays visible instead of being scored as normal.</p>
          </div>
          <div className="context-rail__note">
            <b>Research candidate</b>
            <p>{health?.qualification
              ? `Qualification: ${humanize(health.qualification)}. Allowed role: ${humanize(health.allowed_role ?? "research and evidence labeling")}.`
              : "The sealed evaluation retained 63.1% of attempts, below its 65% target. Independent review precision is unknown; this queue is not operationally qualified."}</p>
          </div>
        </aside>
      </div>
    </main>
  );
}
