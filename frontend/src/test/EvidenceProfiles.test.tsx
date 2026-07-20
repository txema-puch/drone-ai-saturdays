import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ApproachCriterion, ApproachPathPoint } from "../api";
import EvidenceProfiles from "../components/EvidenceProfiles";

const complete = (time: number, crossTrack: number): ApproachPathPoint => ({
  lat: 40.4,
  lon: -3.6,
  time,
  cross_track_m: crossTrack,
  height_above_threshold_m: 100,
  ground_speed_mps: 75,
  vertical_rate_mps: -3,
  track_offset_deg: 2,
});

describe("generated evidence profiles", () => {
  it("shows lateral review evidence as a red signal segment", () => {
    const criteria: ApproachCriterion[] = [{
      name: "lateral_path_proxy",
      status: "review_required",
      evidence: [{ start_time: 0, end_time: 2 }],
    }];
    const { container } = render(
      <EvidenceProfiles path={[complete(0, 500), complete(1, 480), complete(2, 450)]} criteria={criteria} activeIndex={1} />,
    );

    expect(container).toHaveTextContent("Lateral path proxy");
    expect(container.querySelectorAll(".evidence-profiles__line--review")).toHaveLength(2);
  });

  it("does not draw evidence across a missing time interval", () => {
    const { container } = render(
      <EvidenceProfiles path={[complete(0, 10), complete(1, 8), complete(10, 5)]} criteria={[]} activeIndex={1} />,
    );

    expect(container.querySelectorAll(".evidence-profiles__line")).toHaveLength(5);
  });
});
