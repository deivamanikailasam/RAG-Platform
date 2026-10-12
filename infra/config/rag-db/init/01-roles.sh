#!/bin/bash
# One-time bootstrap: extension, schema and least-privilege roles.
# Runs ONLY when the data volume is empty. Later changes go in migrations (dbmate).
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v migrator_pw="$(cat /run/secrets/rag_db_migrator_password)" \
    -v app_pw="$(cat /run/secrets/rag_db_app_password)" \
    -v ro_pw="$(cat /run/secrets/rag_db_readonly_password)" <<'SQL'
-- Extensions (need superuser)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Roles. :'var' safely quotes the password (no SQL injection, never echoed)
CREATE ROLE rag_migrator LOGIN PASSWORD :'migrator_pw';   -- owns the schema, runs migrations
CREATE ROLE rag_app      LOGIN PASSWORD :'app_pw';        -- services: read/write rows only
CREATE ROLE rag_readonly LOGIN PASSWORD :'ro_pw';         -- evaluation/analytics: read only

-- Lock the database down, then grant exactly what's needed
REVOKE ALL ON DATABASE rag FROM PUBLIC;
GRANT CONNECT ON DATABASE rag TO rag_migrator, rag_app, rag_readonly;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

CREATE SCHEMA rag AUTHORIZATION rag_migrator;
GRANT USAGE ON SCHEMA rag TO rag_app, rag_readonly;

-- Tables the migrator creates in future automatically get the right grants
ALTER DEFAULT PRIVILEGES FOR ROLE rag_migrator IN SCHEMA rag
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO rag_app;
ALTER DEFAULT PRIVILEGES FOR ROLE rag_migrator IN SCHEMA rag
    GRANT USAGE, SELECT ON SEQUENCES TO rag_app;
ALTER DEFAULT PRIVILEGES FOR ROLE rag_migrator IN SCHEMA rag
    GRANT SELECT ON TABLES TO rag_readonly;

-- Sensible defaults per role
ALTER ROLE rag_migrator SET search_path = rag, public;
ALTER ROLE rag_app      SET search_path = rag, public;
ALTER ROLE rag_readonly SET search_path = rag, public;
ALTER ROLE rag_app      SET statement_timeout = '30s';     -- no query may run forever
ALTER ROLE rag_readonly SET statement_timeout = '120s';
ALTER ROLE rag_readonly SET default_transaction_read_only = on;
SQL
