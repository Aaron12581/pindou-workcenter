BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE user_status AS ENUM ('active', 'disabled');
CREATE TYPE project_status AS ENUM ('draft', 'processing', 'editable', 'approved', 'exported', 'failed');
CREATE TYPE project_stage AS ENUM ('material', 'two_d', 'board', 'candidate', 'edit', 'export');
CREATE TYPE asset_role AS ENUM ('original', 'cropped', 'removed_bg', 'two_d', 'preview');
CREATE TYPE job_type AS ENUM ('preprocess', 'two_d', 'pattern', 'inspect', 'export');
CREATE TYPE job_status AS ENUM ('queued', 'running', 'succeeded', 'failed', 'canceled');
CREATE TYPE composition_type AS ENUM ('full_body', 'half_body', 'big_head');
CREATE TYPE detail_level AS ENUM ('simple', 'standard', 'rich');
CREATE TYPE outline_mode AS ENUM ('auto_dark', 'none');
CREATE TYPE background_mode AS ENUM ('transparent', 'simplified');
CREATE TYPE candidate_status AS ENUM ('generated', 'selected', 'rejected');
CREATE TYPE board_layout_type AS ENUM ('single', 'double_h', 'double_v', 'quad', 'six_h');
CREATE TYPE board_fit_mode AS ENUM ('contain', 'cover');
CREATE TYPE palette_source_type AS ENUM ('official', 'system');
CREATE TYPE pattern_candidate_type AS ENUM ('low', 'standard', 'rich', 'custom');
CREATE TYPE pattern_status AS ENUM ('generated', 'selected', 'editing', 'approved', 'archived');
CREATE TYPE version_trigger AS ENUM ('candidate_confirmed', 'autosave', 'manual', 'approved', 'pre_export');
CREATE TYPE export_status AS ENUM ('queued', 'running', 'succeeded', 'failed');

CREATE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email varchar(320) NOT NULL UNIQUE,
  display_name varchar(120) NOT NULL,
  status user_status NOT NULL DEFAULT 'active',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE bead_brands (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code varchar(32) NOT NULL UNIQUE,
  name varchar(120) NOT NULL,
  palette_version varchar(64) NOT NULL,
  source_type palette_source_type NOT NULL,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (code, palette_version)
);

CREATE TABLE projects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id uuid NOT NULL REFERENCES users(id),
  name varchar(160) NOT NULL,
  status project_status NOT NULL DEFAULT 'draft',
  current_stage project_stage NOT NULL DEFAULT 'material',
  bead_brand_id uuid REFERENCES bead_brands(id),
  bead_diameter_mm numeric(5,2) NOT NULL DEFAULT 5.00 CHECK (bead_diameter_mm = 5.00),
  cover_asset_id uuid,
  settings jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(settings) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

CREATE TABLE assets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id),
  batch_id uuid,
  sequence_no smallint NOT NULL CHECK (sequence_no BETWEEN 1 AND 10),
  role asset_role NOT NULL,
  parent_asset_id uuid REFERENCES assets(id),
  storage_key varchar(1024) NOT NULL UNIQUE,
  mime_type varchar(64) NOT NULL CHECK (mime_type IN ('image/jpeg', 'image/png', 'image/webp')),
  width_px integer NOT NULL CHECK (width_px > 0),
  height_px integer NOT NULL CHECK (height_px > 0),
  file_size bigint NOT NULL CHECK (file_size > 0),
  sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  alpha_channel boolean NOT NULL DEFAULT false,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  UNIQUE (project_id, batch_id, sequence_no, role)
);

ALTER TABLE projects
  ADD CONSTRAINT projects_cover_asset_fk
  FOREIGN KEY (cover_asset_id) REFERENCES assets(id) DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE generation_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id),
  asset_id uuid REFERENCES assets(id),
  batch_id uuid,
  type job_type NOT NULL,
  status job_status NOT NULL DEFAULT 'queued',
  progress smallint NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
  attempt smallint NOT NULL DEFAULT 0 CHECK (attempt >= 0),
  max_attempts smallint NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 10),
  idempotency_key varchar(160) NOT NULL UNIQUE,
  input_snapshot jsonb NOT NULL CHECK (jsonb_typeof(input_snapshot) = 'object'),
  result jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(result) = 'object'),
  error_code varchar(64),
  error_message text,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (attempt <= max_attempts),
  CHECK ((status = 'failed') OR (error_code IS NULL AND error_message IS NULL)),
  CHECK ((status NOT IN ('succeeded', 'failed', 'canceled')) OR finished_at IS NOT NULL)
);

CREATE TABLE two_d_candidates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id),
  generation_job_id uuid NOT NULL REFERENCES generation_jobs(id),
  source_asset_id uuid NOT NULL REFERENCES assets(id),
  output_asset_id uuid NOT NULL REFERENCES assets(id),
  candidate_no smallint NOT NULL CHECK (candidate_no BETWEEN 1 AND 3),
  composition composition_type NOT NULL,
  detail_level detail_level NOT NULL,
  outline_mode outline_mode NOT NULL DEFAULT 'auto_dark',
  background_mode background_mode NOT NULL DEFAULT 'transparent',
  model_provider varchar(120) NOT NULL,
  model_name varchar(120) NOT NULL,
  model_version varchar(120) NOT NULL,
  prompt_version varchar(64) NOT NULL,
  parameters jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(parameters) = 'object'),
  status candidate_status NOT NULL DEFAULT 'generated',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (generation_job_id, candidate_no)
);

CREATE UNIQUE INDEX one_selected_two_d_candidate_per_project
  ON two_d_candidates(project_id) WHERE status = 'selected';

CREATE TABLE board_plans (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id),
  layout_type board_layout_type NOT NULL,
  board_rows smallint NOT NULL CHECK (board_rows BETWEEN 1 AND 2),
  board_cols smallint NOT NULL CHECK (board_cols BETWEEN 1 AND 3),
  cells_per_board smallint NOT NULL DEFAULT 29 CHECK (cells_per_board = 29),
  grid_width smallint NOT NULL CHECK (grid_width > 0),
  grid_height smallint NOT NULL CHECK (grid_height > 0),
  bead_diameter_mm numeric(5,2) NOT NULL DEFAULT 5.00 CHECK (bead_diameter_mm = 5.00),
  finished_width_mm numeric(8,2) NOT NULL CHECK (finished_width_mm > 0),
  finished_height_mm numeric(8,2) NOT NULL CHECK (finished_height_mm > 0),
  safe_margin_cells smallint NOT NULL DEFAULT 1 CHECK (safe_margin_cells BETWEEN 0 AND 5),
  fit_mode board_fit_mode NOT NULL DEFAULT 'contain',
  subject_scale numeric(8,4) NOT NULL DEFAULT 1 CHECK (subject_scale > 0),
  offset_x numeric(8,3) NOT NULL DEFAULT 0,
  offset_y numeric(8,3) NOT NULL DEFAULT 0,
  board_map jsonb NOT NULL CHECK (jsonb_typeof(board_map) = 'array'),
  confirmed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CHECK (grid_width = board_cols * cells_per_board),
  CHECK (grid_height = board_rows * cells_per_board),
  CHECK (finished_width_mm = grid_width * bead_diameter_mm),
  CHECK (finished_height_mm = grid_height * bead_diameter_mm),
  CHECK (
    (layout_type = 'single' AND board_rows = 1 AND board_cols = 1) OR
    (layout_type = 'double_h' AND board_rows = 1 AND board_cols = 2) OR
    (layout_type = 'double_v' AND board_rows = 2 AND board_cols = 1) OR
    (layout_type = 'quad' AND board_rows = 2 AND board_cols = 2) OR
    (layout_type = 'six_h' AND board_rows = 2 AND board_cols = 3)
  )
);

CREATE UNIQUE INDEX one_active_board_plan_per_project
  ON board_plans(project_id) WHERE deleted_at IS NULL;

CREATE TABLE bead_colors (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  brand_id uuid NOT NULL REFERENCES bead_brands(id),
  color_code varchar(32) NOT NULL,
  color_name varchar(120),
  hex char(7) NOT NULL CHECK (hex ~ '^#[0-9A-Fa-f]{6}$'),
  rgb_r smallint NOT NULL CHECK (rgb_r BETWEEN 0 AND 255),
  rgb_g smallint NOT NULL CHECK (rgb_g BETWEEN 0 AND 255),
  rgb_b smallint NOT NULL CHECK (rgb_b BETWEEN 0 AND 255),
  lab_l numeric(8,4) NOT NULL CHECK (lab_l BETWEEN 0 AND 100),
  lab_a numeric(8,4) NOT NULL,
  lab_b numeric(8,4) NOT NULL,
  source_reference varchar(1024) NOT NULL,
  active boolean NOT NULL DEFAULT true,
  sort_order integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (brand_id, color_code)
);

CREATE TABLE patterns (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id),
  generation_job_id uuid NOT NULL REFERENCES generation_jobs(id),
  board_plan_id uuid NOT NULL REFERENCES board_plans(id),
  source_two_d_id uuid NOT NULL REFERENCES two_d_candidates(id),
  brand_id uuid NOT NULL REFERENCES bead_brands(id),
  candidate_type pattern_candidate_type NOT NULL,
  status pattern_status NOT NULL DEFAULT 'generated',
  width smallint NOT NULL CHECK (width > 0),
  height smallint NOT NULL CHECK (height > 0),
  current_version_id uuid,
  algorithm_version varchar(64) NOT NULL,
  generation_parameters jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(generation_parameters) = 'object'),
  match_score numeric(6,3) CHECK (match_score BETWEEN 0 AND 100),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  UNIQUE (generation_job_id, candidate_type)
);

CREATE TABLE pattern_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  pattern_id uuid NOT NULL REFERENCES patterns(id),
  version_no integer NOT NULL CHECK (version_no > 0),
  trigger version_trigger NOT NULL,
  storage_key varchar(1024) NOT NULL UNIQUE,
  preview_asset_id uuid REFERENCES assets(id),
  checksum char(64) NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
  change_summary jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(change_summary) = 'object'),
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (pattern_id, version_no)
);

ALTER TABLE patterns
  ADD CONSTRAINT patterns_current_version_fk
  FOREIGN KEY (current_version_id) REFERENCES pattern_versions(id)
  DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE export_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id),
  pattern_version_id uuid NOT NULL REFERENCES pattern_versions(id),
  generation_job_id uuid REFERENCES generation_jobs(id),
  status export_status NOT NULL DEFAULT 'queued',
  formats jsonb NOT NULL CHECK (jsonb_typeof(formats) = 'array'),
  contents jsonb NOT NULL CHECK (jsonb_typeof(contents) = 'array'),
  settings jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(settings) = 'object'),
  result_files jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(result_files) = 'array'),
  expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX projects_owner_updated_idx ON projects(owner_id, updated_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX assets_project_sequence_idx ON assets(project_id, sequence_no) WHERE deleted_at IS NULL;
CREATE INDEX assets_batch_idx ON assets(batch_id) WHERE batch_id IS NOT NULL;
CREATE INDEX jobs_project_status_idx ON generation_jobs(project_id, status, created_at DESC);
CREATE INDEX candidates_project_idx ON two_d_candidates(project_id, created_at DESC);
CREATE INDEX colors_brand_active_idx ON bead_colors(brand_id, active, sort_order);
CREATE INDEX patterns_project_status_idx ON patterns(project_id, status, created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX versions_pattern_no_idx ON pattern_versions(pattern_id, version_no DESC);
CREATE INDEX exports_project_created_idx ON export_jobs(project_id, created_at DESC);

CREATE TRIGGER users_set_updated_at BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER bead_brands_set_updated_at BEFORE UPDATE ON bead_brands FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER projects_set_updated_at BEFORE UPDATE ON projects FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER assets_set_updated_at BEFORE UPDATE ON assets FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER generation_jobs_set_updated_at BEFORE UPDATE ON generation_jobs FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER two_d_candidates_set_updated_at BEFORE UPDATE ON two_d_candidates FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER board_plans_set_updated_at BEFORE UPDATE ON board_plans FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER bead_colors_set_updated_at BEFORE UPDATE ON bead_colors FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER patterns_set_updated_at BEFORE UPDATE ON patterns FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER pattern_versions_set_updated_at BEFORE UPDATE ON pattern_versions FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER export_jobs_set_updated_at BEFORE UPDATE ON export_jobs FOR EACH ROW EXECUTE FUNCTION set_updated_at();

INSERT INTO bead_brands (code, name, palette_version, source_type)
VALUES ('MARD', 'MARD', 'official-v1', 'official');

COMMIT;

