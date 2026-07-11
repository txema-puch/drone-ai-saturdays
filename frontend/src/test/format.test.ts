import { describe, expect, it } from "vitest";

import {
  aircraftOf,
  band,
  labelText,
  parseEpoch,
  pctColor,
  scoreColor,
  sparkWidth,
  THRESHOLD,
} from "../lib/format";

describe("scoreColor", () => {
  it("is red at/above 1.0", () => {
    expect(scoreColor(1.0)).toBe("var(--red)");
    expect(scoreColor(2.5)).toBe("var(--red)");
  });
  it("is amber between threshold and 1.0", () => {
    expect(scoreColor(THRESHOLD)).toBe("var(--amber)");
    expect(scoreColor(0.5)).toBe("var(--amber)");
  });
  it("is green below threshold", () => {
    expect(scoreColor(0.0)).toBe("var(--green)");
    expect(scoreColor(THRESHOLD - 0.001)).toBe("var(--green)");
  });
});

describe("pctColor + band (DESIGN.md severity bands)", () => {
  it("maps percentile to the right band boundary", () => {
    expect(band(96)).toBe("highly anomalous");
    expect(pctColor(95)).toBe("var(--red)");
    expect(band(80)).toBe("elevated");
    expect(pctColor(80)).toBe("var(--amber)");
    expect(band(50)).toBe("upper-normal");
    expect(pctColor(50)).toBe("var(--accent)");
    expect(band(49.9)).toBe("normal range");
    expect(pctColor(10)).toBe("var(--green)");
  });
});

describe("sparkWidth", () => {
  it("clamps to [0, 100] over full-scale", () => {
    expect(sparkWidth(0)).toBe(0);
    expect(sparkWidth(2.0)).toBe(100);
    expect(sparkWidth(5.0)).toBe(100);
    expect(sparkWidth(1.0)).toBe(50);
  });
});

describe("parseEpoch", () => {
  it("extracts and formats the unix epoch from a segment id", () => {
    const epoch = Math.floor(Date.UTC(2020, 0, 15, 12, 30, 0) / 1000);
    expect(parseEpoch(`abc123_${epoch}#1`)).toBe("2020-01-15 12:30 UTC");
  });
  it("returns empty for an unparseable id", () => {
    expect(parseEpoch("nope")).toBe("");
  });
});

describe("aircraftOf + labelText", () => {
  it("takes the 6-hex prefix", () => {
    expect(aircraftOf("502ce6_1543855510#1")).toBe("502ce6");
  });
  it("humanizes the label", () => {
    expect(labelText("go_around")).toBe("go-around");
    expect(labelText("emergency")).toBe("emergency");
  });
});
