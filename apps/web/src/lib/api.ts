import axios from "axios";
import type { Job, MaskAssistResult, SessionDetail } from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE ?? "http://localhost:8000/api/v1").replace(/\/+$/, "");

const api = axios.create({
  baseURL: API_BASE
});

export async function createSession(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await api.post<{ session_id: string; source_image_url: string; status: string }>("/sessions", formData, {
    headers: { "Content-Type": "multipart/form-data" }
  });
  return data;
}

export async function getSession(sessionId: string) {
  const { data } = await api.get<SessionDetail>(`/sessions/${sessionId}`);
  return data;
}

export async function lockStyle(sessionId: string, styleId: string) {
  const { data } = await api.post<SessionDetail>(`/sessions/${sessionId}/style/lock`, { style_id: styleId });
  return data;
}

export async function renderSession(sessionId: string, seed?: number) {
  const { data } = await api.post<Job>(`/sessions/${sessionId}/render`, { seed });
  return data;
}

export async function maskAssist(sessionId: string, maskRle: string) {
  const { data } = await api.post<MaskAssistResult>(`/sessions/${sessionId}/mask-assist`, { mask_rle: maskRle });
  return data;
}

export async function createEdit(
  sessionId: string,
  payload: {
    mask_rle: string;
    bbox_x: number;
    bbox_y: number;
    bbox_w: number;
    bbox_h: number;
    seed?: number;
    prompt_override?: string;
  }
) {
  const { data } = await api.post<Job>(`/sessions/${sessionId}/edits`, payload);
  return data;
}

export async function adoptVersion(sessionId: string, versionId: string) {
  const { data } = await api.post<SessionDetail>(`/sessions/${sessionId}/versions/${versionId}/adopt`, {});
  return data;
}

export async function exportSession(sessionId: string) {
  const { data } = await api.post<{ session_id: string; final_image_url: string; manifest_url: string }>(`/sessions/${sessionId}/export`, {});
  return data;
}

export async function getJob(jobId: string) {
  const { data } = await api.get<Job>(`/jobs/${jobId}`);
  return data;
}
