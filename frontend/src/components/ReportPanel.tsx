import { useState } from "react";

interface Props {
  report: string | null;
  model: string | null;
}

/** Analysis report panel. The report is pre-generated at build time (offline LLM) and baked
 *  into the case, so clicking just reveals it — instant, no API call, no key on the Space.
 *  Rendered as PLAIN TEXT (white-space: pre-wrap, never dangerouslySetInnerHTML) so model
 *  output can't inject markup. Explanatory only — labelled so it's never mistaken for scoring. */
export default function ReportPanel({ report, model }: Props) {
  const [shown, setShown] = useState(false);

  if (!report) {
    return (
      <p className="rp-empty sans">
        No analysis report was baked for this case. Run the report-generation workflow, then
        rebuild the audit bundle.
      </p>
    );
  }

  if (!shown) {
    return (
      <button className="rp-btn sans" onClick={() => setShown(true)}>
        ▸ Analyse what drove the score
      </button>
    );
  }

  return (
    <div>
      <p className="rp-text">{report}</p>
      <p className="rp-prov sans">
        AI-generated · {model ?? "llm"} · pre-computed · explanatory analysis, not a model score
      </p>
    </div>
  );
}
