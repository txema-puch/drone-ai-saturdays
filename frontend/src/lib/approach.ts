import type { ApproachStatus } from "../api";

export const STATUS_ORDER: ApproachStatus[] = [
  "review_required",
  "partial_observation",
  "criteria_observed",
  "not_assessable",
];

export const STATUS_COPY: Record<ApproachStatus, { label: string; explanation: string }> = {
  review_required: {
    label: "Review required",
    explanation: "One or more observed approach criteria crossed a configured limit.",
  },
  partial_observation: {
    label: "Partial observation",
    explanation: "Some criteria were assessable, while one or more required channels were unavailable.",
  },
  criteria_observed: {
    label: "Criteria observed",
    explanation: "All required criteria were observed and no persistent limit crossing was found.",
  },
  not_assessable: {
    label: "Not assessable",
    explanation: "The record did not meet the coverage or quality gates required for an assessment.",
  },
};

export function humanize(value: string | null | undefined): string {
  if (!value) return "Unavailable";
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function formatTime(epoch: number | null | undefined): string {
  if (epoch == null || !Number.isFinite(epoch)) return "Time unavailable";
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(epoch * 1000)) + " UTC";
}

export function formatCoverage(
  coverage: number | Record<string, number | string | boolean | null | undefined> | null | undefined,
  observedSamples?: number,
): string {
  if (typeof coverage === "number") {
    const fraction = coverage <= 1 ? coverage : coverage / 100;
    return `${Math.round(fraction * 100)}% observed`;
  }
  if (coverage && typeof coverage.observed_fraction === "number") {
    return `${Math.round(coverage.observed_fraction * 100)}% observed`;
  }
  const samples = observedSamples ?? (coverage && typeof coverage.observed_samples === "number"
    ? coverage.observed_samples
    : undefined);
  return samples == null ? "Coverage unavailable" : `${samples.toLocaleString()} observed rows`;
}

export function shortDigest(value: unknown): string {
  return typeof value === "string" && value ? value.slice(0, 12) : "Unavailable";
}
