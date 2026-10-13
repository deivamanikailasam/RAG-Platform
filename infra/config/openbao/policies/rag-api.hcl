# What rag-api may do (Step 28): fetch its own database credentials and read its own secrets.
# Everything not listed is denied.
path "database/creds/rag-api" {
  capabilities = ["read"]
}

path "database/creds/audit-writer" {
  capabilities = ["read"]
}

path "secret/data/rag-api" {
  capabilities = ["read"]
}
