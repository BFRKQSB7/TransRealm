ALTER TABLE translation_runs ADD COLUMN workflow_definition_snapshot TEXT;

UPDATE translation_runs
SET workflow_definition_snapshot = (
    SELECT definition_json
    FROM workflow_definitions
    WHERE workflow_definitions.id = translation_runs.workflow_id
)
WHERE workflow_definition_snapshot IS NULL;
