// ===== 枚举（来自 services/api/app/models/enums.py）=====

export type ImageStatus = "uploaded" | "queued" | "running" | "succeeded" | "failed";
export type VersionKind = "initial" | "regenerate" | "semantic_edit";
export type JobType = "initial" | "regenerate" | "semantic_edit";
export type JobStatus = "queued" | "running" | "succeeded" | "failed";

// ===== 核心数据模型（来自 services/api/app/schemas/workflow.py）=====

export type VersionRead = {
  id: string;
  image_id: string;
  parent_version_id: string | null;
  kind: string;
  output_url: string;
  user_prompt: string | null;
  seed: number;
  params: Record<string, unknown> | null;
  created_at: string;
};

export type JobRead = {
  id: string;
  type: string;
  batch_id: string | null;
  image_id: string | null;
  status: string;
  progress: number;
  progress_message: string | null;
  error: string | null;
  result_version_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type ImageRead = {
  id: string;
  batch_id: string;
  filename: string;
  original_url: string;
  thumbnail_url: string;
  width: number;
  height: number;
  status: string;
  active_version_id: string | null;
  active_version: VersionRead | null;
  latest_job: JobRead | null;
  created_at: string;
  updated_at: string;
};

export type BatchRead = {
  id: string;
  status: string;
  images: ImageRead[];
  created_at: string;
  updated_at: string;
};

// ===== 请求体（来自 workflow.py）=====

export type RegenerateRequest = {
  seed?: number;
};

export type SemanticEditRequest = {
  version_id: string;
  user_prompt: string;
  seed?: number;
};

export type ExportRequest = {
  image_ids?: string[];
};

// ===== 响应体（来自 workflow.py）=====

export type UploadResponse = {
  batch_id: string;
  images: ImageRead[];
};

export type JobsResponse = {
  jobs: JobRead[];
};

export type VersionsResponse = {
  image_id: string;
  active_version_id: string | null;
  versions: VersionRead[];
};

export type ExportResponse = {
  batch_id: string;
  zip_url: string;
};

// ===== 参考图审核（来自 reference_review.py）=====

export type ReferenceReviewImageRead = {
  file_name: string;
  relative_path: string;
};

export type ReferenceReviewRead = {
  directory: string;
  current: ReferenceReviewImageRead | null;
  next: ReferenceReviewImageRead | null;
  pending_count: number;
  keep_count: number;
  discard_count: number;
  reviewed_count: number;
  total_count: number;
  history_count: number;
  keep_hotkey: string;
  discard_hotkey: string;
  undo_hotkey: string;
  preview_max_edge: number;
};

export type ReferenceReviewActionRequest = {
  directory: string;
  relative_path: string;
  action: "keep" | "discard";
};

export type ReferenceReviewUndoRequest = {
  directory: string;
};
