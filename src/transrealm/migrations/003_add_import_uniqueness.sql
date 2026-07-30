CREATE UNIQUE INDEX uq_source_documents_project_hash
ON source_documents(project_id, source_hash);

CREATE UNIQUE INDEX uq_segments_document_stable_key
ON segments(source_document_id, stable_key);
