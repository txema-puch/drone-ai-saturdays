import { Navigate, Route, Routes } from "react-router-dom";

import CaseFile from "./pages/CaseFile";
import Operation from "./pages/Operation";
import Queue from "./pages/Queue";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Queue />} />
      <Route path="/operation/:operationRef" element={<Operation />} />
      <Route path="/case/:id" element={<CaseFile />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
