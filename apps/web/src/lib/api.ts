import axios from "axios";
import type { Job, SessionDetail } from "./types";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE ?? "http://localhost:8000/api/v1"
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

export async function segmentSession(sessionId: string, seed?: number, cropCount = 6) {
  const { data } = await api.post<Job>(`/sessions/${sessionId}/segment`, { seed, crop_count: cropCount });
  return data;
}

export async function lockStyle(sessionId: string, styleId: string) {
  const { data } = await api.post<SessionDetail>(`/sessions/${sessionId}/style/lock`, { style_id: styleId });
  return data;
}

export async function generateCrops(sessionId: string) {
  const { data } = await api.post<Job>(`/sessions/${sessionId}/crops/generate`, { force_regenerate_missing: true });
  return data;
}

export async function resetGeneration(sessionId: string) {
  const { data } = await api.post<SessionDetail>(`/sessions/${sessionId}/reset-generation`, {});
  return data;
}

export async function regenerateCrop(cropId: string, seed?: number) {
  const { data } = await api.post<Job>(`/crops/${cropId}/regenerate`, { seed });
  return data;
}

export async function approveCrop(cropId: string) {
  const { data } = await api.post<SessionDetail>(`/crops/${cropId}/approve`, {});
  return data;
}

export async function composeSession(sessionId: string) {
  const { data } = await api.post<Job>(`/sessions/${sessionId}/compose`, { seam_pass_count: 1 });
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
