-- Project-scoped glossary entries (V1.0).
-- Each project maintains its own glossary; a source term is unique within a
-- project so the deterministic locked-entry injection in M03 never sees
-- ambiguous duplicates. scope is a user-editable category label; priority is
-- 0-100 with higher meaning more important (05 §4/5: high priority injected
-- first, low priority pruned first). V1.0 injects only locked entries.
CREATE TABLE glossary_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    source_term TEXT NOT NULL,
    target_term TEXT NOT NULL,
    scope TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 50 CHECK(priority BETWEEN 0 AND 100),
    is_locked INTEGER NOT NULL DEFAULT 0 CHECK(is_locked IN (0, 1)),
    origin TEXT NOT NULL CHECK(origin IN ('user', 'import')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_id, source_term),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX idx_glossary_entries_project_priority
    ON glossary_entries(project_id, priority);
