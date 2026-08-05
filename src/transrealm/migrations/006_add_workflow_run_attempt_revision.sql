CREATE TABLE workflow_definitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    origin TEXT NOT NULL CHECK(origin IN ('builtin', 'user')),
    parent_workflow_id INTEGER,
    version TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    definition_hash TEXT NOT NULL,
    is_read_only INTEGER NOT NULL DEFAULT 0 CHECK(is_read_only IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(name, version)
);

CREATE INDEX idx_workflow_definitions_name ON workflow_definitions(name);

CREATE TABLE translation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    workflow_id INTEGER NOT NULL,
    workflow_version TEXT NOT NULL,
    workflow_definition_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running' CHECK(status IN ('running', 'completed', 'failed', 'cancelled')),
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (workflow_id) REFERENCES workflow_definitions(id) ON DELETE RESTRICT
);

CREATE INDEX idx_translation_runs_project ON translation_runs(project_id);
CREATE INDEX idx_translation_runs_workflow ON translation_runs(workflow_id);

CREATE TABLE segment_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    segment_id INTEGER NOT NULL,
    claim_version INTEGER NOT NULL,
    lease_owner TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    model_profile_id INTEGER NOT NULL,
    profile_snapshot TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    context_summary TEXT NOT NULL,
    validator_summary TEXT NOT NULL,
    request_id TEXT,
    status TEXT NOT NULL DEFAULT 'created' CHECK(status IN ('created', 'succeeded', 'failed', 'cancelled')),
    retryable INTEGER NOT NULL DEFAULT 0 CHECK(retryable IN (0, 1)),
    input_tokens INTEGER,
    output_tokens INTEGER,
    latency_ms INTEGER,
    error_type TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    FOREIGN KEY (run_id) REFERENCES translation_runs(id) ON DELETE CASCADE,
    FOREIGN KEY (segment_id) REFERENCES segments(id) ON DELETE CASCADE,
    FOREIGN KEY (model_profile_id) REFERENCES model_profiles(id) ON DELETE RESTRICT
);

CREATE INDEX idx_segment_attempts_segment ON segment_attempts(segment_id, created_at);

CREATE TABLE translation_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    origin TEXT NOT NULL CHECK(origin IN ('ai', 'user', 'import')),
    attempt_id INTEGER,
    is_locked INTEGER NOT NULL DEFAULT 0 CHECK(is_locked IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (segment_id) REFERENCES segments(id) ON DELETE CASCADE,
    FOREIGN KEY (attempt_id) REFERENCES segment_attempts(id) ON DELETE SET NULL
);

CREATE INDEX idx_translation_revisions_segment ON translation_revisions(segment_id, created_at);
