#!/bin/bash
# One-time bootstrap for the AUDIT database (Step 23): a separate database with its own roles.
# Runs automatically on an empty volume; on an existing one run `just audit-bootstrap` once.
# Later changes go in migrations (infra/db/audit/migrations, applied by audit_migrator).
set -euo pipefail
SECRETS_DIR="${SECRETS_DIR:-/run/secrets}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    -v migrator_pw="$(cat "$SECRETS_DIR/audit_db_migrator_password")" \
    -v writer_pw="$(cat "$SECRETS_DIR/audit_db_writer_password")" \
    -v reader_pw="$(cat "$SECRETS_DIR/audit_db_reader_password")" <<'SQL'
-- Three roles, three jobs. None of them is a superuser.
CREATE ROLE audit_migrator LOGIN PASSWORD :'migrator_pw';   -- owns the schema, runs migrations
CREATE ROLE audit_writer   LOGIN PASSWORD :'writer_pw';     -- rag-api: may ONLY call audit.append()
CREATE ROLE audit_reader   LOGIN PASSWORD :'reader_pw';     -- verifier/anchor job, auditors: read only

-- A separate database: no rag role (not even rag_migrator) can connect to it
CREATE DATABASE audit OWNER audit_migrator;
REVOKE ALL ON DATABASE audit FROM PUBLIC;
GRANT CONNECT ON DATABASE audit TO audit_migrator, audit_writer, audit_reader;

ALTER ROLE audit_writer SET statement_timeout = '5s';       -- an audit write must be quick
ALTER ROLE audit_reader SET statement_timeout = '600s';     -- verifying a long chain takes a while
ALTER ROLE audit_reader SET default_transaction_read_only = on;
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname audit <<'SQL'
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA audit AUTHORIZATION audit_migrator;
GRANT USAGE ON SCHEMA audit TO audit_writer, audit_reader;
-- Postgres lets EVERY role execute a new function by default. Switch that off for this owner:
-- each function is granted explicitly in the migration, to exactly the role that needs it.
ALTER DEFAULT PRIVILEGES FOR ROLE audit_migrator REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER ROLE audit_migrator IN DATABASE audit SET search_path = audit;
ALTER ROLE audit_writer   IN DATABASE audit SET search_path = audit;
ALTER ROLE audit_reader   IN DATABASE audit SET search_path = audit;
SQL
