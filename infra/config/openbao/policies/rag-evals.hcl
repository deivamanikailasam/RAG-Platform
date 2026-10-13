# The evaluation harness (Step 26): read-only database access and its gateway key.
path "database/creds/rag-readonly" {
  capabilities = ["read"]
}

path "secret/data/rag-evals" {
  capabilities = ["read"]
}
