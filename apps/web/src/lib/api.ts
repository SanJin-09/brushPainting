import axios from "axios";
import type {
  UploadResponse,
  BatchRead,
  JobsResponse,
  JobRead,
  VersionsResponse,
  ExportResponse,
  RegenerateRequest,
  SemanticEditRequest,
  ExportRequest,
  SegmentRequest,
  SegmentsResponse,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE ?? "http://localhost:8000/api").replace(/\/+$/, "");
const SERVICE_BASE = API_BASE.endsWith("/api") ? API_BASE.slice(0, -4) : "";
const AUTH_REQUIRED_EVENT = "brush-auth-required";
const CSRF_STORAGE_KEY = "brush-csrf-token";

export type AuthStatus = {
  auth_required: boolean;
  authenticated: boolean;
  csrf_token: string | null;
};

let csrfToken = sessionStorage.getItem(CSRF_STORAGE_KEY);

const api = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
});

const authApi = axios.create({
  baseURL: SERVICE_BASE,
  withCredentials: true,
});

function updateCsrfToken(token: string | null) {
  csrfToken = token;
  if (token) {
    sessionStorage.setItem(CSRF_STORAGE_KEY, token);
  } else {
    sessionStorage.removeItem(CSRF_STORAGE_KEY);
  }
}

api.interceptors.request.use((config) => {
  const method = config.method?.toUpperCase() ?? "GET";
  if (csrfToken && !["GET", "HEAD", "OPTIONS"].includes(method)) {
    config.headers["X-CSRF-Token"] = csrfToken;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      updateCsrfToken(null);
      window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));
    }
    return Promise.reject(error);
  },
);

export function onAuthenticationRequired(listener: () => void) {
  window.addEventListener(AUTH_REQUIRED_EVENT, listener);
  return () => window.removeEventListener(AUTH_REQUIRED_EVENT, listener);
}

export async function getAuthStatus() {
  const { data } = await authApi.get<AuthStatus>("/auth/status");
  updateCsrfToken(data.csrf_token);
  return data;
}

export async function createAuthSession(apiKey: string) {
  const { data } = await authApi.post<AuthStatus>(
    "/auth/session",
    undefined,
    { headers: { "X-API-Key": apiKey } },
  );
  updateCsrfToken(data.csrf_token);
  return data;
}

export async function deleteAuthSession() {
  try {
    await authApi.delete(
      "/auth/session",
      { headers: csrfToken ? { "X-CSRF-Token": csrfToken } : undefined },
    );
  } finally {
    updateCsrfToken(null);
  }
}

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

export async function segmentImage(imageId: string, body: SegmentRequest) {
  const { data } = await api.post<JobRead>(`/images/${imageId}/segment`, body);
  return data;
}

export async function getImageSegments(imageId: string, userPrompt?: string) {
  const { data } = await api.get<SegmentsResponse>(`/images/${imageId}/segments`, {
    params: userPrompt ? { user_prompt: userPrompt } : undefined,
  });
  return data;
}
