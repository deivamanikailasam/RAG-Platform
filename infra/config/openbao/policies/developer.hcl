# A person working on the platform (Step 28): a short-lived READ-ONLY database login when they
# need to look at data (just vault-creds rag-readonly). Every issue is in the audit log.
path "database/creds/rag-readonly" {
  capabilities = ["read"]
}
