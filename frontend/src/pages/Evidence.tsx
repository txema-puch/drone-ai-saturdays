import { useEffect, useState } from "react";

import {
  getEvidence,
  type AggregateCell,
  type ContextValidationFinding,
  type ResearchCohort,
  type ResearchEvidence,
  type ScreeningHoldoutFinding,
} from "../api";
import { humanize } from "../lib/approach";

function count(value: AggregateCell | number | null): string {
  if (value === "<10") return "Fewer than 10 (suppressed)";
  if (value === "suppressed") return "Suppressed to protect a small companion cell";
  if (value == null) return "Not published";
  return value.toLocaleString();
}

function rate(value: number | null): string {
  if (value == null) {
    return "Not published because its numerator or denominator is suppressed";
  }
  return `${(value * 100).toFixed(1)}%`;
}

function CountRows({ values }: { values: Record<string, AggregateCell> | null }) {
  if (!values) return <tr><th scope="row">Counts</th><td>Not published</td></tr>;
  return <>{Object.entries(values).map(([label, value]) => (
    <tr key={label}><th scope="row">{humanize(label)}</th><td>{count(value)}</td></tr>
  ))}</>;
}

function Limits({ items, label }: { items: string[]; label: string }) {
  return <div className="evidence-limits sans"><h4>{label}</h4><ul>{items.map((item) => <li key={item}>{item}</li>)}</ul></div>;
}

function CountTable({ caption, values }: { caption: string; values: Record<string, AggregateCell> }) {
  return (
    <div className="evidence-table-scroll" tabIndex={0} aria-label={`${caption} table`}>
      <table><caption>{caption}</caption><tbody><CountRows values={values} /></tbody></table>
    </div>
  );
}

function CriterionCountsTable({
  caption,
  values,
}: {
  caption: string;
  values: Record<string, Record<string, AggregateCell>>;
}) {
  return (
    <div className="evidence-table-scroll" tabIndex={0} aria-label={`${caption} table`}>
      <table>
        <caption>{caption}</caption>
        <thead><tr><th scope="col">Criterion</th><th scope="col">Status</th><th scope="col">Attempts</th></tr></thead>
        <tbody>{Object.entries(values).flatMap(([criterion, statuses]) => (
          Object.entries(statuses).map(([status, value]) => (
            <tr key={`${criterion}-${status}`}><th scope="row">{humanize(criterion)}</th><td>{humanize(status)}</td><td>{count(value)}</td></tr>
          ))
        ))}</tbody>
      </table>
    </div>
  );
}

function CohortTables({ cohort }: { cohort: ResearchCohort }) {
  return (
    <article className="evidence-cohort">
      <div className="section-heading sans">
        <div><p className="eyebrow">{humanize(cohort.role)}</p><h3>{cohort.period}</h3></div>
        <span className="mono">{cohort.cohort_id}</span>
      </div>
      <div className="evidence-table-scroll" tabIndex={0} aria-label={`${cohort.period} cohort summary table`}>
        <table>
          <caption>{cohort.period} source and assessment totals</caption>
          <tbody>
            <tr><th scope="row">Rows</th><td>{count(cohort.rows)}</td></tr>
            <tr><th scope="row">Operations</th><td>{count(cohort.operations)}</td></tr>
            <tr><th scope="row">Operations with attempts</th><td>{count(cohort.operations_with_attempts)}</td></tr>
            <tr><th scope="row">Attempts</th><td>{count(cohort.attempts)}</td></tr>
            <tr><th scope="row">Assessable attempts</th><td>{count(cohort.assessable_attempts)}</td></tr>
            <tr><th scope="row">Abstention rate</th><td>{rate(cohort.abstention_rate)}</td></tr>
            <tr><th scope="row">Review rate among assessable attempts</th><td>{rate(cohort.review_rate_among_assessable)}</td></tr>
          </tbody>
        </table>
      </div>
      <div className="evidence-count-grid">
        <div className="evidence-table-scroll" tabIndex={0} aria-label={`${cohort.period} status counts table`}>
          <table><caption>Status counts</caption><tbody><CountRows values={cohort.status_counts} /></tbody></table>
        </div>
        <div className="evidence-table-scroll" tabIndex={0} aria-label={`${cohort.period} outcome counts table`}>
          <table><caption>Outcome counts</caption><tbody><CountRows values={cohort.outcome_counts} /></tbody></table>
        </div>
      </div>
      <CriterionCountsTable caption="Criterion status counts" values={cohort.criterion_status_counts} />
      <Limits items={cohort.interpretation_limits} label={`${cohort.period} interpretation limits`} />
    </article>
  );
}

function ScreeningFinding({ finding }: { finding: ScreeningHoldoutFinding }) {
  return (
    <article className="evidence-cohort">
      <div className="section-heading sans"><div><p className="eyebrow">Frozen holdout</p><h3>Screening behavior</h3></div><span className="mono">{finding.cohort_id}</span></div>
      <p><b>Policy:</b> {humanize(finding.policy)}.</p>
      <CountTable caption="Reasons evidence was incomplete" values={finding.reason_counts} />
      <CriterionCountsTable caption="Holdout criterion status counts" values={finding.criterion_status_counts} />
      <Limits items={finding.interpretation_limits} label="Holdout interpretation limits" />
    </article>
  );
}

function ContextFinding({ finding }: { finding: ContextValidationFinding }) {
  return (
    <article className="evidence-cohort">
      <div className="section-heading sans"><div><p className="eyebrow">Context validation</p><h3>Reference comparison</h3></div><span className="mono">{finding.cohort_id}</span></div>
      <p><b>Decision:</b> {humanize(finding.decision)}.</p>
      <div className="evidence-table-scroll" tabIndex={0} aria-label="Base and context review rates table">
        <table><caption>Review rate among assessable attempts</caption><tbody>
          <tr><th scope="row">Base reference</th><td>{rate(finding.base_review_rate_among_assessable)}</td></tr>
          <tr><th scope="row">Context reference</th><td>{rate(finding.context_review_rate_among_assessable)}</td></tr>
        </tbody></table>
      </div>
      <div className="evidence-count-grid">
        <CountTable caption="Base status counts" values={finding.base_status_counts} />
        <CountTable caption="Context status counts" values={finding.context_status_counts} />
      </div>
      <div className="evidence-count-grid">
        <CriterionCountsTable caption="Base criterion status counts" values={finding.base_criterion_status_counts} />
        <CriterionCountsTable caption="Context criterion status counts" values={finding.context_criterion_status_counts} />
      </div>
      <div className="evidence-count-grid">
        <CountTable caption="Review overlap" values={finding.review_overlap} />
        <CountTable caption="Status transitions" values={finding.status_transition_counts} />
      </div>
      <div className="evidence-table-scroll" tabIndex={0} aria-label="Context coverage table">
        <table><caption>Context coverage</caption><tbody>{Object.entries(finding.context_coverage).map(([label, value]) => (
          <tr key={label}><th scope="row">{humanize(label)}</th><td>{rate(value)}</td></tr>
        ))}</tbody></table>
      </div>
      <Limits items={finding.interpretation_limits} label="Context comparison interpretation limits" />
    </article>
  );
}

export default function Evidence() {
  const [evidence, setEvidence] = useState<ResearchEvidence | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setEvidence(null);
    setError(null);
    getEvidence(controller.signal).then(setEvidence).catch((reason: unknown) => {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setError(reason instanceof Error ? reason.message : "Research evidence is unavailable.");
    });
    return () => controller.abort();
  }, [retry]);

  if (error) return (
    <main className="workspace"><div className="state-panel state-panel--page" role="alert">
      <p className="eyebrow">Real aggregate research</p><h1>Research evidence unavailable</h1>
      <p>{error}</p><button type="button" onClick={() => setRetry((value) => value + 1)}>Retry research evidence</button>
    </div></main>
  );

  if (!evidence) return (
    <main className="workspace evidence-workspace" aria-busy="true" aria-label="Loading research evidence">
      <div className="loading-line loading-line--short" /><div className="loading-line loading-line--title" /><div className="loading-panel" />
    </main>
  );

  const notice = evidence.data_access.publication_notice_status === "pending"
    ? "Publication notice is pending."
    : `Publication notice: ${humanize(evidence.data_access.publication_notice_status)}.`;

  return (
    <main className="workspace evidence-workspace">
      <header className="workspace-header">
        <div><p className="eyebrow">Real aggregate research</p><h1>Research evidence</h1>
          <p className="workspace-subtitle sans">Published cohort findings remain separate from the generated demonstration cases.</p></div>
        <div className="cohort-summary sans"><span>Evidence basis</span><b>Aggregate real data</b><small>Generated {evidence.generated_at}</small></div>
      </header>

      <section className="evidence-copy" aria-labelledby="real-title">
        <p className="eyebrow">01 · Origin</p><h2 id="real-title">What is real here</h2>
        <p>Counts and rates on this page were computed from real OpenSky research cohorts. No individual trajectory or source record is published here.</p>
      </section>

      <section className="evidence-copy" aria-labelledby="cohorts-title">
        <p className="eyebrow">02 · Results</p><h2 id="cohorts-title">Cohorts</h2>
        <div className="evidence-cohorts">{evidence.cohorts.map((cohort) => <CohortTables cohort={cohort} key={cohort.cohort_id} />)}</div>
      </section>

      <section className="evidence-copy" aria-labelledby="meaning-title">
        <p className="eyebrow">03 · Interpretation</p><h2 id="meaning-title">What findings mean</h2>
        <p>These findings describe rule behavior, reference behavior, evidence coverage and potential review workload. They do not measure whether a verdict is correct.</p>
        <div className="evidence-cohorts">
          <ScreeningFinding finding={evidence.findings.screening_holdout} />
          <ContextFinding finding={evidence.findings.context_validation} />
        </div>
      </section>

      <section className="evidence-copy" aria-labelledby="missing-title">
        <p className="eyebrow">04 · Limits</p><h2 id="missing-title">What is missing</h2>
        <p>There are no independent human labels, so precision and recall are not available. This evidence does not support a safety claim, emergency-detection claim or operational qualification.</p>
        <dl className="result-facts sans">
          <div><dt>Qualification</dt><dd>{humanize(evidence.qualification)}</dd></div>
          <div><dt>Allowed role</dt><dd>{humanize(evidence.allowed_role)}</dd></div>
        </dl>
        <Limits items={evidence.blocked_uses.map(humanize)} label="Blocked uses" />
        <Limits items={evidence.limitations} label="Release limitations" />
      </section>

      <section className="evidence-copy" aria-labelledby="access-title">
        <p className="eyebrow">05 · Source access</p><h2 id="access-title">How to access source data</h2>
        <p>SADAR does not redistribute the underlying records. Obtain data directly from OpenSky and follow its current terms.</p>
        <p className="evidence-links sans"><a href={evidence.data_access.access_url} target="_blank" rel="noreferrer">OpenSky data access</a><a href={evidence.data_access.terms_url} target="_blank" rel="noreferrer">OpenSky terms of use</a></p>
      </section>

      <section className="evidence-copy" aria-labelledby="citation-title">
        <p className="eyebrow">06 · Attribution</p><h2 id="citation-title">Citation and publication notice</h2>
        <blockquote>{evidence.data_access.citation}</blockquote>
        <p><b>{notice}</b>{evidence.data_access.publication_notice_date ? ` Notice date: ${evidence.data_access.publication_notice_date}.` : " No notice date is recorded."}</p>
      </section>

      <section className="evidence-copy" aria-labelledby="demo-title">
        <p className="eyebrow">07 · Demonstration lane</p><h2 id="demo-title">How demo cases differ</h2>
        <p>Synthetic cases teach the interface and make specific rule behaviors inspectable. Their scenario mix is curated for learning and must not be interpreted as prevalence in real operations.</p>
      </section>
    </main>
  );
}
