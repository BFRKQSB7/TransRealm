ALTER TABLE source_documents ADD COLUMN raw_bytes BLOB;
ALTER TABLE source_documents ADD COLUMN format_metadata TEXT;

-- Logical reuse identity includes format and parser identity/version so the
-- same bytes in different formats (or different parser contracts) do not
-- wrongly reuse one SourceDocument. 003's (project_id, source_hash) index is
-- replaced here; existing rows already satisfy the relaxed domain.
CREATE UNIQUE INDEX uq_source_documents_project_hash_format_parser
ON source_documents(project_id, source_hash, format, parser_version);

DROP INDEX uq_source_documents_project_hash;
