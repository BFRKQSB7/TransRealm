-- Project interaction mode (auto vs workbench). Defaults to the safe "auto"
-- mode for both new and pre-existing projects; schema_version stays 1 because
-- the column is additive and never changes existing rows' meaning.
ALTER TABLE projects ADD COLUMN mode TEXT NOT NULL DEFAULT 'auto'
    CHECK (mode IN ('auto', 'workbench'));
