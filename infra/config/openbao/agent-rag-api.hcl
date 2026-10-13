# OpenBao Agent beside rag-api (Step 28): logs in with AppRole, keeps fresh credentials in files.
# rag-api never talks to OpenBao and never holds an OpenBao token.
pid_file = ""

vault {
  address = "http://openbao:8200"
}

auto_auth {
  method "approle" {
    mount_path = "auth/approle"
    config = {
      role_id_file_path                   = "/openbao/bootstrap/role_id"           # not secret: WHICH role
      secret_id_file_path                 = "/openbao/bootstrap/secret_id"         # a WRAPPING token, not the secret itself
      secret_id_response_wrapping_path    = "auth/approle/role/rag-api/secret-id"  # unwrap it: works exactly once
      remove_secret_id_file_after_reading = true                                   # and don't leave it lying around
    }
  }
}

template_config {
  exit_on_retry_failure = true # can't fetch secrets? stop: rag-api must not run on stale ones
}

# Database logins: a username AND password made for this agent, expiring on their own.
# The agent fetches a new pair before the old one expires and replaces the file in one step.
template {
  contents             = "{{ with secret \"database/creds/rag-api\" }}{{ .Data | toJSON }}{{ end }}"
  destination          = "/openbao/out/rag_db.json"
  perms                = "0400"
  error_on_missing_key = true
}

template {
  contents             = "{{ with secret \"database/creds/audit-writer\" }}{{ .Data | toJSON }}{{ end }}"
  destination          = "/openbao/out/audit_db.json"
  perms                = "0400"
  error_on_missing_key = true
}

# Static secrets, one file each, named the way rag-api's settings read them (Step 17)
template {
  contents             = "{{ with secret \"secret/data/rag-api\" }}{{ .Data.data.gateway_key }}{{ end }}"
  destination          = "/openbao/out/rag_api_gateway_key"
  perms                = "0400"
  error_on_missing_key = true
}

template {
  contents             = "{{ with secret \"secret/data/rag-api\" }}{{ .Data.data.opa_token }}{{ end }}"
  destination          = "/openbao/out/rag_api_opa_token"
  perms                = "0400"
  error_on_missing_key = true
}

# Step 31: what the ingestion worker (same identity as rag-api, Step 37 separates them) needs
template {
  contents             = "{{ with secret \"secret/data/rag-api\" }}{{ .Data.data.valkey_url }}{{ end }}"
  destination          = "/openbao/out/valkey_url"
  perms                = "0400"
  error_on_missing_key = true
}

template {
  contents             = "{{ with secret \"secret/data/rag-api\" }}[default]\naws_access_key_id = {{ .Data.data.s3_access_key }}\naws_secret_access_key = {{ .Data.data.s3_secret_key }}\n{{ end }}"
  destination          = "/openbao/out/aws_credentials"
  perms                = "0400"
  error_on_missing_key = true
}
