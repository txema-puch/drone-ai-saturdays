import { describe, expect, it } from "vitest";

import { geoBounds, makeProjector, projectTracks, toPoints } from "../lib/geo";

const PATH = [
  { lat: 40.49, lon: -3.59, alt: 1000 },
  { lat: 40.45, lon: -3.57, alt: 500 },
  { lat: 40.52, lon: -3.61, alt: 2000 },
];

describe("geoBounds", () => {
  it("captures lat/lon extent and a cos(lat) scale", () => {
    const b = geoBounds(PATH);
    expect(b.minLat).toBeCloseTo(40.45);
    expect(b.maxLat).toBeCloseTo(40.52);
    expect(b.minLon).toBeCloseTo(-3.61);
    expect(b.maxLon).toBeCloseTo(-3.57);
    expect(b.k).toBeGreaterThan(0);
    expect(b.k).toBeLessThan(1);
  });
});

describe("makeProjector", () => {
  it("keeps every projected point inside the padded viewport", () => {
    const proj = makeProjector(geoBounds(PATH), 560, 360, 34);
    for (const p of PATH) {
      const { x, y } = proj.project(p);
      expect(x).toBeGreaterThanOrEqual(33);
      expect(x).toBeLessThanOrEqual(527);
      expect(y).toBeGreaterThanOrEqual(33);
      expect(y).toBeLessThanOrEqual(327);
    }
  });
  it("flips latitude so north is up (higher lat → smaller y)", () => {
    const proj = makeProjector(geoBounds(PATH), 560, 360, 34);
    const north = proj.y(40.52);
    const south = proj.y(40.45);
    expect(north).toBeLessThan(south);
  });
});

describe("toPoints + projectTracks", () => {
  it("emits one 'x,y' pair per point", () => {
    const proj = makeProjector(geoBounds(PATH), 560, 360, 34);
    const pts = toPoints(PATH, proj);
    expect(pts.split(" ")).toHaveLength(PATH.length);
    expect(pts).toMatch(/^[\d.]+,[\d.]+/);
  });
  it("projectTracks returns empty arrays for empty input without throwing", () => {
    expect(projectTracks([[]], 100, 100)).toEqual([[]]);
  });
});
