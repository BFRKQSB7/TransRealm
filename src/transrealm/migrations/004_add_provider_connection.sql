CREATE TABLE provider_connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    provider_type TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    timeout_seconds INTEGER NOT NULL,
    max_retries INTEGER NOT NULL DEFAULT 0,
    retry_delay_seconds REAL NOT NULL DEFAULT 0.0,
    credential_reference TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_provider_connections_name ON provider_connections(name);
