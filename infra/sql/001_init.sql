CREATE TABLE IF NOT EXISTS sessions (
  id UUID PRIMARY KEY,
  source_image_url TEXT NOT NULL,
  style_id TEXT,
  status TEXT NOT NULL,
  seed BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS crops (
  id UUID PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  bbox_x INTEGER NOT NULL,
  bbox_y INTEGER NOT NULL,
  bbox_w INTEGER NOT NULL,
  bbox_h INTEGER NOT NULL,
  mask_rle TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS crop_versions (
  id UUID PRIMARY KEY,
  crop_id UUID NOT NULL REFERENCES crops(id) ON DELETE CASCADE,
  version_no INTEGER NOT NULL,
  image_url TEXT NOT NULL,
  seed BIGINT NOT NULL,
  params_hash TEXT NOT NULL,
  approved BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(crop_id, version_no)
);

CREATE TABLE IF NOT EXISTS compose_results (
  id UUID PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  image_url TEXT NOT NULL,
  seam_pass_count INTEGER NOT NULL DEFAULT 1,
  quality_score DOUBLE PRECISION,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS jobs (
  id UUID PRIMARY KEY,
  type TEXT NOT NULL,
  session_id UUID REFERENCES sessions(id) ON DELETE SET NULL,
  payload_json JSONB,
  status TEXT NOT NULL,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crops_session_id ON crops(session_id);
CREATE INDEX IF NOT EXISTS idx_crop_versions_crop_id ON crop_versions(crop_id);
CREATE INDEX IF NOT EXISTS idx_jobs_session_id ON jobs(session_id);
