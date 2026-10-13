-- Step 28 cut-over: once rag-api reads OpenBao credentials, the shared group roles stop logging in.
-- They keep all their privileges: every short-lived user is created IN ROLE one of them.
-- Run with: just vault-cutover          Undo (rollback to static passwords): just vault-cutover-undo
ALTER ROLE rag_app      NOLOGIN;
ALTER ROLE rag_readonly NOLOGIN;
ALTER ROLE audit_writer NOLOGIN;
