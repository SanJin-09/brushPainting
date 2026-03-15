export type ImageVersion = {
  id: string;
  session_id: string;
  parent_version_id: string | null;
  kind: "FULL_RENDER" | "LOCAL_EDIT";
  image_url: string;
  seed: number;
  params_hash: string;
  is_current: boolean;
  prompt_override: string | null;
  mask_rle: string | null;
  bbox_x: number | null;
  bbox_y: number | null;
  bbox_w: number | null;
  bbox_h: number | null;
  created_at: string;
};

export type SessionDetail = {
  id: string;
  source_image_url: string;
  style_id: string | null;
  status: string;
  seed: number | null;
  current_version_id: string | null;
  created_at: string;
  updated_at: string;
  versions: ImageVersion[];
};

export type MaskAssistResult = {
  mask_rle: string;
  bbox_x: number;
  bbox_y: number;
  bbox_w: number;
  bbox_h: number;
};

export type Job = {
  id: string;
  type: string;
  session_id: string | null;
  status: string;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

export type ReferenceReviewImage = {
  file_name: string;
  relative_path: string;
};

export type ReferenceReviewState = {
  directory: string;
  current: ReferenceReviewImage | null;
  pending_count: number;
  keep_count: number;
  discard_count: number;
  reviewed_count: number;
  total_count: number;
  history_count: number;
  keep_hotkey: string;
  discard_hotkey: string;
  undo_hotkey: string;
};
