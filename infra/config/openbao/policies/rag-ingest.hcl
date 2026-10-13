# What the ingestion worker and the lifecycle jobs may do (Step 37): their own database leases, their
# own secrets (gateway key for embeddings, Valkey for the queue, object storage for the originals,
# the PII key) and read-only audit access for online evaluation. Nothing of rag-api's.
path "database/creds/rag-ingest" {
  capabilities = ["read"]
}

path "database/creds/audit-reader" {
  capabilities = ["read"]
}

path "secret/data/rag-ingest" {
  capabilities = ["read"]
}
