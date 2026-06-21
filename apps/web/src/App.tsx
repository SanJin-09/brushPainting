import React from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import AuthGate from "./components/AuthGate";
import NavBar from "./components/NavBar";
import UploadPage from "./pages/UploadPage";
import BatchDetailPage from "./pages/BatchDetailPage";
import ImageDetailPage from "./pages/ImageDetailPage";
import ExportPage from "./pages/ExportPage";

export default function App() {
  return (
    <AuthGate>
      <NavBar />
      <Routes>
        <Route path="/" element={<UploadPage />} />
        <Route path="/batches/:batchId" element={<BatchDetailPage />} />
        <Route path="/batches/:batchId/images/:imageId" element={<ImageDetailPage />} />
        <Route path="/batches/:batchId/export" element={<ExportPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthGate>
  );
}
