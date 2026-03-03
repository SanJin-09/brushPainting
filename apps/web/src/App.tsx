import React from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import ExportPage from "./pages/ExportPage";
import SessionPage from "./pages/SessionPage";
import UploadPage from "./pages/UploadPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<UploadPage />} />
      <Route path="/sessions/:id" element={<SessionPage />} />
      <Route path="/sessions/:id/export" element={<ExportPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
