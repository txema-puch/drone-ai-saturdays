import { scoreColor, sparkWidth } from "../lib/format";

/** A 4px reconstruction-error sparkbar — non-color severity cue paired with the
 *  numeric score (DESIGN.md: severity survives colorblindness via length too). */
export default function Sparkbar({ score, threshold }: { score: number; threshold?: number }) {
  const color = scoreColor(score, threshold);
  return (
    <div
      style={{
        height: 4,
        borderRadius: 99,
        background: "var(--map-bg)",
        marginTop: 5,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          height: "100%",
          borderRadius: 99,
          width: `${sparkWidth(score)}%`,
          background: color,
        }}
      />
    </div>
  );
}
