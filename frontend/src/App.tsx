import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import CaseFile from "./pages/CaseFile";
import Evaluate from "./pages/Evaluate";
import Evidence from "./pages/Evidence";
import Operation from "./pages/Operation";
import Queue from "./pages/Queue";
import "./pages/approach.css";

export default function App() {
  return (
    <div className="app-shell">
      <div className="app-chrome">
        <header className="app-nav sans">
          <NavLink className="app-brand" to="/" aria-label="SADAR Analyst Console home">
            SADAR <span>/ ANALYST CONSOLE</span>
          </NavLink>
          <nav aria-label="Primary navigation">
            <NavLink to="/" end>Attempts</NavLink>
            <NavLink to="/evaluate">Evaluate data</NavLink>
            <NavLink to="/evidence">Research evidence</NavLink>
          </nav>
        </header>
        <div className="app-boundary sans" role="note" aria-label="Data origin and research qualification">
          <b>Synthetic demo cases · Real research results shown only in aggregate.</b>
          <span>Not operationally qualified. Use for evidence inspection and labeling only.</span>
        </div>
      </div>
      <div className="app-content">
        <Routes>
          <Route path="/" element={<Queue />} />
          <Route path="/approaches/:attemptId" element={<CaseFile />} />
          <Route path="/approach-operations/:operationRef" element={<Operation />} />
          <Route path="/evaluate" element={<Evaluate />} />
          <Route path="/evidence" element={<Evidence />} />
          <Route path="/case/:attemptId" element={<CaseFile />} />
          <Route path="/operation/:operationRef" element={<Operation />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </div>
  );
}
