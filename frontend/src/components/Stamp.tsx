import type { Label } from "../api";
import { labelText } from "../lib/format";

/** Category stamp (NORMAL / GO-AROUND / EMERGENCY). The text label is itself a
 *  non-color severity cue. */
export default function Stamp({
  label,
  rotate = false,
  style,
}: {
  label: Label;
  rotate?: boolean;
  style?: React.CSSProperties;
}) {
  return (
    <span
      className={`stamp ${label}`}
      style={{ transform: rotate ? "rotate(-1.5deg)" : undefined, ...style }}
    >
      {labelText(label)}
    </span>
  );
}
