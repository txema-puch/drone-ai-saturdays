/** Per-feature reconstruction-error attribution — which channel drove the
 *  score. Diagnostic only (never a tuning knob, per the feature contract). */
export default function Attribution({ attribution }: { attribution: Record<string, number> }) {
  const rows = Object.entries(attribution)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);
  const max = rows.length ? rows[0][1] : 1;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
      {rows.map(([feature, value]) => (
        <div
          key={feature}
          className="sans"
          style={{
            display: "grid",
            gridTemplateColumns: "120px 1fr 46px",
            alignItems: "center",
            gap: 10,
            fontSize: 14,
          }}
        >
          <span>{feature}</span>
          <div
            style={{
              height: 8,
              background: "var(--map-bg)",
              borderRadius: 99,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                height: "100%",
                borderRadius: 99,
                width: `${Math.max(3, (value / (max || 1)) * 100)}%`,
                background: "linear-gradient(90deg, var(--accent), var(--amber))",
              }}
            />
          </div>
          <span
            className="mono"
            style={{ textAlign: "right", color: "var(--mut)" }}
          >
            {value.toFixed(2)}
          </span>
        </div>
      ))}
    </div>
  );
}
