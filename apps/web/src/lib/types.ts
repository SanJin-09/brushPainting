export type ImageStatus = "uploaded" | "queued" | "running" | "succeeded" | "failed";
export type VersionKind = "initial" | "regenerate" | "semantic_edit";
export type JobType = "initial" | "regenerate" | "semantic_edit" | "sam_segment";
export type JobStatus = "queued" | "running" | "succeeded" | "failed";

export type VersionRead = {
  id: string;
  image_id: string;
  parent_version_id: string | null;
  kind: VersionKind;
  output_url: string;
  user_prompt: string | null;
  seed: number;
  params: Record<string, unknown> | null;
  created_at: string;
};

export type JobRead = {
  id: string;
  type: JobType;
  batch_id: string | null;
  image_id: string | null;
  status: JobStatus;
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
  status: ImageStatus;
  active_version_id: string | null;
  active_version: VersionRead | null;
  latest_job: JobRead | null;
  created_at: string;
  updated_at: string;
};

export type BatchRead = {
  id: string;
  status: ImageStatus;
  images: ImageRead[];
  created_at: string;
  updated_at: string;
};

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

export type SegmentRequest = {
  user_prompt: string;
};

export type SegmentRead = {
  id: string;
  source_image_id: string;
  user_prompt: string;
  region_index: number;
  confidence: number;
  mask_url: string | null;
  crop_url: string;
  bbox_x: number;
  bbox_y: number;
  bbox_w: number;
  bbox_h: number;
  area_ratio: number;
  created_at: string;
};

export type SegmentsResponse = {
  source_image_id: string;
  user_prompt: string;
  segments: SegmentRead[];
};
