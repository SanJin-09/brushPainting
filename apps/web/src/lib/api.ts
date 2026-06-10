import axios from "axios";
import type {
  UploadResponse,
  BatchRead,
  JobsResponse,
  JobRead,
  VersionsResponse,
  ExportResponse,
  ReferenceReviewRead,
  RegenerateRequest,
  SemanticEditRequest,
  ExportRequest,
  ReferenceReviewActionRequest,
  ReferenceReviewUndoRequest,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE ?? "http://localhost:8000/api").replace(/\/+$/, "");

const api = axios.create({
  baseURL: API_BASE
});

//主流程接口

export async function uploadImages(files: File[]) {
  const formData = new FormData();
  files.forEach((f) => formData.append("files", f));
  const { data } = await api.post<UploadResponse>("/images/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" }
  });
  return data;
}

export async function getBatch(batchId: string) {
  const { data } = await api.get<BatchRead>(`/batches/${batchId}`);
  return data;
}

export async function generateBatch(batchId: string) {
  const { data } = await api.post<JobsResponse>(`/batches/${batchId}/generate`);
  return data;
}

export async function regenerateImage(imageId: string, body?: RegenerateRequest) {
  const { data } = await api.post<JobRead>(`/images/${imageId}/regenerate`, body ?? {});
  return data;
}

export async function semanticEdit(imageId: string, body: SemanticEditRequest) {
  const { data } = await api.post<JobRead>(`/images/${imageId}/edit`, body);
  return data;
}

export async function getJob(jobId: string) {
  const { data } = await api.get<JobRead>(`/jobs/${jobId}`);
  return data;
}

export async function getImageVersions(imageId: string) {
  const { data } = await api.get<VersionsResponse>(`/images/${imageId}/versions`);
  return data;
}

export async function exportBatch(batchId: string, body?: ExportRequest) {
  const { data } = await api.post<ExportResponse>(`/batches/${batchId}/export`, body ?? {});
  return data;
}

// ===== 参考图审核接口 =====

export async function getReferenceReview(directory: string) {
  const { data } = await api.get<ReferenceReviewRead>("/reference-review", { params: { directory } });
  return data;
}

export async function applyReferenceReviewAction(payload: ReferenceReviewActionRequest) {
  const { data } = await api.post<ReferenceReviewRead>("/reference-review/action", payload);
  return data;
}

export async function undoReferenceReview(directory: string) {
  const body: ReferenceReviewUndoRequest = { directory };
  const { data } = await api.post<ReferenceReviewRead>("/reference-review/undo", body);
  return data;
}

export function getReferenceReviewImageUrl(directory: string, relativePath: string, maxEdge?: number) {
  const params = new URLSearchParams({ directory, relative_path: relativePath });
  if (maxEdge) {
    params.set("max_edge", String(maxEdge));
  }
  return `${API_BASE}/reference-review/image?${params.toString()}`;
}
