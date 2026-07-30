CREATE TABLE model_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    provider_connection_id INTEGER NOT NULL,
    model_id TEXT NOT NULL,
    template_version TEXT NOT NULL,
    output_protocol TEXT NOT NULL,
    context_budget TEXT NOT NULL,
    default_params TEXT NOT NULL,
    capability_snapshot TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (provider_connection_id) REFERENCES provider_connections(id) ON DELETE RESTRICT
);

CREATE INDEX idx_model_profiles_name ON model_profiles(name);
CREATE INDEX idx_model_profiles_connection ON model_profiles(provider_connection_id);
