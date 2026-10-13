#!/bin/bash
# One-time bootstrap for OpenBao (Step 28): the database logins that OpenBao uses to create
# short-lived users (one per database). Runs automatically on an empty volume; on an existing one:
# just vault-db-bootstrap.
# The password below is only a bootstrap value: `just vault-setup` rotates it straight away,
# after which only OpenBao knows these passwords.
set -euo pipefail
SECRETS_DIR="${SECRETS_DIR:-/run/secrets}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    -v admin_pw="$(cat "$SECRETS_DIR/vault_admin_pg_password")" <<'SQL'
-- One login per database connection in OpenBao. Each one's password is rotated separately,
-- so they can't share a login (rotating one would break the other).
-- CREATEROLE lets them create and drop roles, but they are NOT superusers: each can only hand out
-- membership of the groups it was given WITH ADMIN OPTION (a Postgres 16 rule).
CREATE ROLE vault_admin_rag   LOGIN CREATEROLE PASSWORD :'admin_pw';
CREATE ROLE vault_admin_audit LOGIN CREATEROLE PASSWORD :'admin_pw';
GRANT rag_app, rag_readonly TO vault_admin_rag   WITH ADMIN OPTION;
GRANT audit_writer          TO vault_admin_audit WITH ADMIN OPTION;
-- Step 37: online evaluation reads the audit log with short-lived audit_reader leases
GRANT audit_reader          TO vault_admin_audit WITH ADMIN OPTION;
-- revoking a lease ends that user's open sessions first (pg_terminate_backend)
GRANT pg_signal_backend TO vault_admin_rag, vault_admin_audit;
GRANT CONNECT ON DATABASE rag   TO vault_admin_rag;
GRANT CONNECT ON DATABASE audit TO vault_admin_audit;
ALTER ROLE vault_admin_rag   SET statement_timeout = '10s';
ALTER ROLE vault_admin_audit SET statement_timeout = '10s';
SQL
