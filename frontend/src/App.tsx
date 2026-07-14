import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import { getHealth } from "./api";
import CaseFile from "./pages/CaseFile";
import Evaluate from "./pages/Evaluate";
import Operation from "./pages/Operation";
import Queue from "./pages/Queue";

export default function App() {
  const [evaluationEnabled, setEvaluationEnabled] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal)
      .then((health) => setEvaluationEnabled(health.evaluation_enabled === true))
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  return (
    <div className="app-shell">
      <header className="app-nav sans">
        <NavLink className="app-brand" to="/">SADAR <span>/ LEMD CONFORMANCE</span></NavLink>
        <nav aria-label="Primary navigation">
          <NavLink to="/" end>Audit queue</NavLink>
          {evaluationEnabled && <NavLink to="/evaluate">Evaluate data</NavLink>}
        </nav>
      </header>
      <div className="app-content">
        <Routes>
          <Route path="/" element={<Queue />} />
          <Route path="/operation/:operationRef" element={<Operation />} />
          <Route path="/case/:caseId" element={<CaseFile />} />
          <Route path="/evaluate" element={<Evaluate />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </div>
  );
}
