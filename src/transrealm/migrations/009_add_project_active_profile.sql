-- Project can select a single active ModelProfile (V1.0).
-- 1:1 single-valued selection uses a nullable FK column rather than a
-- normalized table; ON DELETE RESTRICT prevents deleting a profile that is
-- active in any project (DB-level backstop for the service pre-check).
ALTER TABLE projects ADD COLUMN active_profile_id INTEGER
    REFERENCES model_profiles(id) ON DELETE RESTRICT;
