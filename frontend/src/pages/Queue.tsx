import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FixedSizeList as List, type ListChildComponentProps } from "react-window";

import {
  getFlights,
  getHealth,
  getOperations,
  type FlightSummary,
  type Health,
  type Label,
  type OperationSummary,
  type Order,
  type ReviewLane,
} from "../api";
import Sparkbar from "../components/Sparkbar";
import Stamp from "../components/Stamp";
import { aircraftOf, parseEpoch, pctColor, scoreColor } from "../lib/format";
import { useElementHeight } from "../lib/useElementSize";
import "./queue.css";

type CategoryFilter = "all" | "go_around" | "emergency";
type ThresholdFilter = "above" | "all";
type LaneFilter = ReviewLane | "all";
type QueueMode = "operations" | "segments";

const SEGMENT_ROW_HEIGHT = 56;
const OPERATION_ROW_HEIGHT = 72;
const GRID = "110px 1fr 64px 132px 104px";

interface SegmentRowData {
  rows: FlightSummary[];
  open: (id: number) => void;
}

function SegmentRow({ index, style, data }: ListChildComponentProps<SegmentRowData>) {
  const segment = data.rows[index];
  const interactive = segment.has_case;
  return (
    <div
      style={{ ...style, gridTemplateColumns: GRID }}
      className={`q-row${interactive ? " q-row--open" : ""}`}
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      aria-label={
        interactive
          ? `Open case file for segment ${segment.segment_id}, percentile ${Math.round(segment.pct)}, score ${segment.score.toFixed(2)}, ${segment.label}`
          : undefined
      }
      onClick={interactive ? () => data.open(segment.id) : undefined}
      onKeyDown={interactive ? (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          data.open(segment.id);
        }
      } : undefined}
    >
      <div className="q-cno">
        {segment.case_ref}
        <small>{parseEpoch(segment.segment_id)}</small>
      </div>
      <div>
        <div className="q-sid mono">{segment.segment_id}</div>
        <small className="q-sub sans">
          aircraft {aircraftOf(segment.segment_id)} · scored segment
          {!interactive && " · no case file"}
        </small>
      </div>
      <div className="q-pct sans" style={{ color: pctColor(segment.pct) }}>
        {Math.round(segment.pct)}
        <small style={{ color: "var(--mut)", fontWeight: 400 }}>th</small>
      </div>
      <div className="q-scorebox">
        <div className="q-sv" style={{ color: scoreColor(segment.score) }}>
          {segment.score.toFixed(2)}
        </div>
        <Sparkbar score={segment.score} />
      </div>
      <Stamp label={segment.label} style={{ justifySelf: "end" }} />
    </div>
  );
}

interface OperationRowData {
  rows: OperationSummary[];
  open: (operationRef: string) => void;
  lane: LaneFilter;
}

function OperationRow({ index, style, data }: ListChildComponentProps<OperationRowData>) {
  const operation = data.rows[index];
  const laneSegments = data.lane === "all"
    ? operation.segments
    : operation.segments.filter((segment) => segment.review_lane === data.lane);
  const worst = laneSegments.reduce(
    (current, segment) => !current || segment.score > current.score ? segment : current,
    undefined as FlightSummary | undefined,
  );
  const label: Label = worst?.label ?? "normal";
  const flaggedCount = laneSegments.filter((segment) => segment.anomalous).length;
  const flaggedCopy = `${flaggedCount} flagged ${flaggedCount === 1 ? "segment" : "segments"} in this ${data.lane === "all" ? "operation" : data.lane.replace("_", " ") + " lane"}`;
  return (
    <div
      style={{ ...style, gridTemplateColumns: GRID }}
      className="q-row q-row--operation q-row--open"
      role="button"
      tabIndex={0}
      aria-label={`Open operation ${operation.operation_ref}`}
      onClick={() => data.open(operation.operation_ref)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          data.open(operation.operation_ref);
        }
      }}
    >
      <div className="q-cno">
        {operation.operation_ref}
        <small>{operation.segment_count} total segments</small>
      </div>
      <div>
        <div className="q-sid sans">{flaggedCopy}</div>
        <small className="q-sub sans">
          {worst ? `Lane evidence: ${worst.case_ref}` : "No evidence in this lane"} · Labels: {operation.labels_seen.join(", ")} · Assessment: {operation.assessment_summary}
        </small>
      </div>
      <div className="q-pct sans" style={{ color: pctColor(worst?.pct ?? 0) }}>
        {Math.round(worst?.pct ?? 0)}
        <small style={{ color: "var(--mut)", fontWeight: 400 }}>th</small>
      </div>
      <div className="q-scorebox">
        <div className="q-sv" style={{ color: scoreColor(worst?.score ?? 0) }}>
          {(worst?.score ?? 0).toFixed(2)}
        </div>
        <Sparkbar score={worst?.score ?? 0} />
      </div>
      <Stamp label={label} style={{ justifySelf: "end" }} />
    </div>
  );
}

export default function Queue() {
  const navigate = useNavigate();
  const [health, setHealth] = useState<Health | null>(null);
  const [segments, setSegments] = useState<FlightSummary[] | null>(null);
  const [operations, setOperations] = useState<OperationSummary[] | null>(null);
  const [error, setError] = useState(false);
  const [mode, setMode] = useState<QueueMode>("operations");
  const [order, setOrder] = useState<Order>("anomalous");
  const [category, setCategory] = useState<CategoryFilter>("all");
  const [threshold, setThreshold] = useState<ThresholdFilter>("all");
  const [lane, setLane] = useState<LaneFilter>("behavioral");
  const [search, setSearch] = useState("");
  const { ref: listWrap, height: listHeight } = useElementHeight<HTMLDivElement>(640);

  useEffect(() => {
    const ctrl = new AbortController();
    setSegments(null);
    setOperations(null);
    setError(false);
    Promise.all([
      getHealth(ctrl.signal),
      getFlights(5000, order, ctrl.signal),
      getOperations(5000, order, ctrl.signal),
    ])
      .then(([healthResponse, segmentResponse, operationResponse]) => {
        setHealth(healthResponse);
        setSegments(segmentResponse);
        setOperations(operationResponse);
      })
      .catch((responseError) => {
        if (responseError?.name !== "AbortError") setError(true);
      });
    return () => ctrl.abort();
  }, [order]);

  const segmentRows = useMemo(() => {
    if (!segments) return [];
    const query = search.trim().toLowerCase();
    return segments.filter((segment) => {
      if (query && ![segment.segment_id, segment.case_ref, segment.operation_ref].some((value) => value.toLowerCase().includes(query))) return false;
      if (category !== "all" && segment.label !== category) return false;
      if (threshold === "above" && !segment.anomalous) return false;
      if (lane !== "all" && segment.review_lane !== lane) return false;
      return true;
    });
  }, [segments, search, category, threshold, lane]);

  const operationRows = useMemo(() => {
    if (!operations) return [];
    const query = search.trim().toLowerCase();
    const filtered = operations.filter((operation) => {
      const laneSegments = lane === "all"
        ? operation.segments
        : operation.segments.filter((segment) => segment.review_lane === lane);
      const matchesSearch = [operation.operation_ref, operation.worst_case_ref, ...operation.segments.map((segment) => segment.segment_id)]
        .some((value) => value.toLowerCase().includes(query));
      if (query && !matchesSearch) return false;
      if (category !== "all" && !operation.labels_seen.includes(category)) return false;
      if (threshold === "above" && !laneSegments.some((segment) => segment.anomalous)) return false;
      if (lane === "behavioral" && operation.reviewable_segment_count === 0) return false;
      if (lane === "data_quality" && operation.data_quality_segment_count === 0) return false;
      if (lane === "coverage" && operation.coverage_limited_segment_count === 0) return false;
      return true;
    });
    if (lane === "behavioral") return filtered;

    const laneScore = (operation: OperationSummary) => Math.max(
      ...operation.segments
        .filter((segment) => lane === "all" || segment.review_lane === lane)
        .map((segment) => segment.score),
    );
    const scores = filtered.map(laneScore).sort((a, b) => a - b);
    const median = scores.length ? scores[Math.floor(scores.length / 2)] : 0;
    return [...filtered].sort((left, right) => {
      const leftScore = laneScore(left);
      const rightScore = laneScore(right);
      if (order === "normal") return leftScore - rightScore;
      if (order === "typical") {
        return Math.abs(leftScore - median) - Math.abs(rightScore - median);
      }
      return rightScore - leftScore;
    });
  }, [operations, search, category, threshold, lane, order]);

  const loaded = segments !== null && operations !== null;
  const visibleCount = mode === "operations" ? operationRows.length : segmentRows.length;
  const totalCount = mode === "operations" ? operations?.length ?? 0 : segments?.length ?? 0;
  const rowHeight = mode === "operations" ? OPERATION_ROW_HEIGHT : SEGMENT_ROW_HEIGHT;
  const openSegment = (id: number) => navigate(`/case/${id}`);
  const openOperation = (operationRef: string) => navigate(`/operation/${encodeURIComponent(operationRef)}`);

  return (
    <div className="q-wrap">
      <aside className="q-meta">
        <fieldset className="q-grp">
          <legend className="microlabel">View</legend>
          <div className="q-mode" role="group" aria-label="Queue level">
            <button className={`q-mode-btn sans${mode === "operations" ? " on" : ""}`} aria-pressed={mode === "operations"} onClick={() => setMode("operations")}>Operations</button>
            <button className={`q-mode-btn sans${mode === "segments" ? " on" : ""}`} aria-pressed={mode === "segments"} onClick={() => setMode("segments")}>Segments</button>
          </div>
        </fieldset>
        <div className="q-grp">
          <h2 className="microlabel">Search</h2>
          <input className="q-search mono" placeholder="ref or segment id…" value={search} onChange={(event) => setSearch(event.target.value)} aria-label="Search queue" />
        </div>
        <fieldset className="q-grp">
          <legend className="microlabel">Order</legend>
          {([["anomalous", "Most anomalous"], ["typical", "Typical"], ["normal", "Least"]] as const).map(([value, label]) => (
            <button key={value} className={`q-opt sans${order === value ? " on" : ""}`} aria-pressed={order === value} onClick={() => setOrder(value)}>{label}</button>
          ))}
        </fieldset>
        <fieldset className="q-grp">
          <legend className="microlabel">Category</legend>
          {([["all", "All"], ["go_around", "Go-around"], ["emergency", "Emergency"]] as const).map(([value, label]) => (
            <button key={value} className={`q-opt sans${category === value ? " on" : ""}`} aria-pressed={category === value} onClick={() => setCategory(value)}>{label}</button>
          ))}
        </fieldset>
        <fieldset className="q-grp">
          <legend className="microlabel">Filter</legend>
          {([["above", "Above threshold"], ["all", "All segments"]] as const).map(([value, label]) => (
            <button key={value} className={`q-opt sans${threshold === value ? " on" : ""}`} aria-pressed={threshold === value} onClick={() => setThreshold(value)}>{label}</button>
          ))}
        </fieldset>
        <fieldset className="q-grp">
          <legend className="microlabel">Review lane</legend>
          {([["behavioral", "Behavioral review"], ["data_quality", "Data quality"], ["coverage", "Coverage limited"], ["all", "All evidence"]] as const).map(([value, label]) => (
            <button key={value} className={`q-opt sans${lane === value ? " on" : ""}`} aria-pressed={lane === value} onClick={() => setLane(value)}>{label}</button>
          ))}
        </fieldset>
      </aside>

      <main className="q-main">
        <div className="q-hd">
          <h1>Conformance Audit — LEMD</h1>
          <div className="q-docket sans">
            {health ? <><b>{health.operations.toLocaleString()}</b> operations · <b>{health.segments.toLocaleString()}</b> scored segments · <b>{health.reviewable.toLocaleString()}</b> reviewable · <b>{health.data_quality_conflicts + health.insufficient_data}</b> data-quality review · <b>{health.coverage_limited}</b> coverage-limited</> : "Loading audit summary…"}
          </div>
        </div>

        <div className="q-colhd sans" style={{ gridTemplateColumns: GRID }}>
          <span>{mode === "operations" ? "Operation" : "Case"}</span>
          <span>{mode === "operations" ? "Segment evidence" : "Segment"}</span>
          <span className="r">Lane pctile</span>
          <span className="r">{mode === "operations" ? "Lane score" : "Score"}</span>
          <span className="r">Category</span>
        </div>

        <div className="q-list" ref={listWrap}>
          {error ? (
            <div className="q-empty sans"><div className="big">Cannot reach the audit service</div>The serve layer on :8077 is not responding.<div><button className="q-retry sans" onClick={() => setOrder((current) => current)}>Retry</button></div></div>
          ) : !loaded ? (
            <div aria-busy="true" aria-label="Loading queue">{Array.from({ length: 10 }).map((_, index) => <div key={index} className="q-skel" style={{ height: rowHeight }} />)}</div>
          ) : visibleCount === 0 ? (
            <div className="q-empty sans"><div className="big">No matching {mode}</div>No {mode} match this search and filter. Clear the search or widen the filter to see the full docket.</div>
          ) : mode === "operations" ? (
            <List height={listHeight} itemCount={operationRows.length} itemSize={OPERATION_ROW_HEIGHT} width="100%" itemData={{ rows: operationRows, open: openOperation, lane }} overscanCount={8}>{OperationRow}</List>
          ) : (
            <List height={listHeight} itemCount={segmentRows.length} itemSize={SEGMENT_ROW_HEIGHT} width="100%" itemData={{ rows: segmentRows, open: openSegment }} overscanCount={8}>{SegmentRow}</List>
          )}
        </div>

        <div className="q-foot sans">
          {loaded ? <>Showing {visibleCount.toLocaleString()} of {totalCount.toLocaleString()} {mode} · {lane.replace("_", " ")} lane · virtualized</> : "Connecting to :8077…"}
        </div>
      </main>
    </div>
  );
}
