import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import CaseFile from "./pages/CaseFile";
import Evaluate from "./pages/Evaluate";
import Operation from "./pages/Operation";
import Queue from "./pages/Queue";
import "./pages/approach.css";

export default function App() {
  return (
    <div className="app-shell">
      <header className="app-nav sans">
        <NavLink className="app-brand" to="/" aria-label="SADAR Analyst Console home">
          SADAR <span>/ ANALYST CONSOLE</span>
        </NavLink>
        <nav aria-label="Primary navigation">
          <NavLink to="/" end>Attempts</NavLink>
          <NavLink to="/evaluate">Evaluate data</NavLink>
        </nav>
      </header>
      <div className="app-content">
        <Routes>
          <Route path="/" element={<Queue />} />
          <Route path="/approaches/:attemptId" element={<CaseFile />} />
          <Route path="/approach-operations/:operationRef" element={<Operation />} />
          <Route path="/evaluate" element={<Evaluate />} />
          <Route path="/case/:attemptId" element={<CaseFile />} />
          <Route path="/operation/:operationRef" element={<Operation />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </div>
  );
}
