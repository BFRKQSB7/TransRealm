-- One current, user-authored Notes value per Project/Job. An empty value is
-- represented by no row; Project deletion removes its Notes automatically.
CREATE TABLE project_notes (
    project_id INTEGER PRIMARY KEY,
    content TEXT NOT NULL CHECK(length(trim(content)) > 0),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);
