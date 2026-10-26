-- ==============================================================================
-- KVIT Policy Intelligence - Phase 4: PostgreSQL Row-Level Security (RLS) Setup
-- ==============================================================================
-- Architecture:
-- 1. Creates dedicated non-owner application role 'kvit_app_user' without BYPASSRLS.
-- 2. ENABLES and FORCES Row-Level Security on documents and chunks tables.
-- 3. Policy evaluates current_setting('app.current_role', true) against allowed_roles JSONB.
-- 4. If app.current_role is unset (NULL), exactly 0 rows are visible.
-- 5. The application executes `SET LOCAL app.current_role = :role` inside each transaction.
-- ==============================================================================

-- 1. Create Application Role (Non-Owner, No BypassRLS)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kvit_app_user') THEN
        CREATE ROLE kvit_app_user WITH
            LOGIN
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            NOBYPASSRLS
            PASSWORD 'kvit_app_password';
        RAISE NOTICE 'Created application role kvit_app_user without BYPASSRLS.';
    ELSE
        ALTER ROLE kvit_app_user WITH NOBYPASSRLS;
        RAISE NOTICE 'Updated application role kvit_app_user to enforce NOBYPASSRLS.';
    END IF;
END $$;

-- 2. Grant Minimum Required Permissions to Application Role
GRANT USAGE ON SCHEMA public TO kvit_app_user;
GRANT SELECT ON documents TO kvit_app_user;
GRANT SELECT ON chunks TO kvit_app_user;
GRANT SELECT ON document_lineage TO kvit_app_user;
GRANT SELECT ON chunks_semantic TO kvit_app_user;

-- 3. Enable and FORCE Row-Level Security on Documents Table
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;

-- Drop existing policy if present
DROP POLICY IF EXISTS documents_role_governance_policy ON documents;

-- Create Documents RLS Policy
-- When app.current_role is not set, current_setting(..., true) returns NULL, matching 0 rows.
CREATE POLICY documents_role_governance_policy ON documents
FOR SELECT
TO kvit_app_user
USING (
    allowed_roles::jsonb ? current_setting('app.current_role', true)
    OR allowed_roles::jsonb ? 'all'
);

-- 4. Enable and FORCE Row-Level Security on Chunks Table
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks FORCE ROW LEVEL SECURITY;

-- Drop existing policy if present
DROP POLICY IF EXISTS chunks_role_governance_policy ON chunks;

-- Create Chunks RLS Policy
CREATE POLICY chunks_role_governance_policy ON chunks
FOR SELECT
TO kvit_app_user
USING (
    allowed_roles::jsonb ? current_setting('app.current_role', true)
    OR allowed_roles::jsonb ? 'all'
);

-- 5. Verification Instructions:
-- Test 1 (Zero Rows Unset):
--   SET ROLE kvit_app_user;
--   SELECT set_config('app.current_role', '', true);
--   SELECT count(*) FROM chunks; -- EXPECTED: 0
--
-- Test 2 (Student Scope):
--   SELECT set_config('app.current_role', 'student', true);
--   SELECT count(*) FROM chunks; -- EXPECTED: Student-permitted chunks only
--
-- Test 3 (Admin Scope):
--   SELECT set_config('app.current_role', 'admin', true);
--   SELECT count(*) FROM chunks; -- EXPECTED: All corpus chunks

