export const KNOTS_PER_MPS = 1.943844;
export const FEET_PER_MINUTE_PER_MPS = 196.850394;

export function roundedKnots(value: number): number {
  return Math.round(value * KNOTS_PER_MPS);
}
