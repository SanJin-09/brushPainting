CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  source_image_url TEXT NOT NULL,
  style_id TEXT,
  status TEXT NOT NULL,
  seed BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS image_versions (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  parent_version_id TEXT REFERENCES image_versions(id) ON DELETE SET NULL,
  kind TEXT NOT NULL,
  image_url TEXT NOT NULL,
  seed BIGINT NOT NULL,
  params_hash TEXT NOT NULL,
  is_current BOOLEAN NOT NULL DEFAULT FALSE,
  prompt_override TEXT,
  mask_rle TEXT,
  bbox_x INTEGER,
  bbox_y INTEGER,
  bbox_w INTEGER,
  bbox_h INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
  payload_json JSONB,
  status TEXT NOT NULL,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_image_versions_session_id ON image_versions(session_id);
CREATE INDEX IF NOT EXISTS idx_jobs_session_id ON jobs(session_id);
