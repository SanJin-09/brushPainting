export type CropVersion = {
  id: string;
  version_no: number;
  image_url: string;
  seed: number;
  params_hash: string;
  approved: boolean;
  created_at: string;
};

export type Crop = {
  id: string;
  bbox_x: number;
  bbox_y: number;
  bbox_w: number;
  bbox_h: number;
  status: string;
  created_at: string;
  versions: CropVersion[];
};

export type ComposeResult = {
  id: string;
  image_url: string;
  seam_pass_count: number;
  quality_score: number | null;
  created_at: string;
};

export type SessionDetail = {
  id: string;
  source_image_url: string;
  style_id: string | null;
  status: string;
  seed: number | null;
  created_at: string;
  updated_at: string;
  crops: Crop[];
  compose_results: ComposeResult[];
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
