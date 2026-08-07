-- Per-profile Prompt Override (read-only preset + user's saved copy).
-- 1:1 with model_profiles; deleting a profile cascades its override. The
-- parent_template_version records which preset version the override is based on
-- so a stale override (parent changed by an app update) is rejected fail-closed.
-- schema_version stays 1 because the column set is additive and never changes
-- existing rows' meaning.
CREATE TABLE prompt_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_profile_id INTEGER NOT NULL,
    parent_template_version TEXT NOT NULL,
    template_text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (model_profile_id) REFERENCES model_profiles(id) ON DELETE CASCADE,
    UNIQUE (model_profile_id)
);
