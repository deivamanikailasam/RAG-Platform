# OpenBao Agent inside the ingestion worker and lifecycle jobs (Step 37): role "rag-ingest".
pid_file = ""

vault {
  address = "http://openbao:8200"
}

auto_auth {
  method "jwt" {
    mount_path = "auth/kubernetes-jwt"
    config = {
      role = "rag-ingest"
      path = "/var/run/secrets/openbao/token"
      remove_jwt_after_reading = false
    }
  }
}

template_config {
  exit_on_retry_failure = true
}

template {
  contents             = "{{ with secret \"database/creds/rag-ingest\" }}{{ .Data | toJSON }}{{ end }}"
  destination          = "/openbao/out/rag_db.json"
  perms                = "0400"
  error_on_missing_key = true
}

template {
  contents             = "{{ with secret \"secret/data/rag-ingest\" }}{{ .Data.data.gateway_key }}{{ end }}"
  destination          = "/openbao/out/rag_api_gateway_key"
  perms                = "0400"
  error_on_missing_key = true
}

template {
  contents             = "{{ with secret \"secret/data/rag-ingest\" }}{{ .Data.data.valkey_url }}{{ end }}"
  destination          = "/openbao/out/valkey_url"
  perms                = "0400"
  error_on_missing_key = true
}

template {
  contents             = "{{ with secret \"secret/data/rag-ingest\" }}[default]\naws_access_key_id = {{ .Data.data.s3_access_key }}\naws_secret_access_key = {{ .Data.data.s3_secret_key }}\n{{ end }}"
  destination          = "/openbao/out/aws_credentials"
  perms                = "0400"
  error_on_missing_key = true
}

template {
  contents             = "{{ with secret \"secret/data/rag-ingest\" }}{{ .Data.data.pii_hmac_key }}{{ end }}"
  destination          = "/openbao/out/pii_hmac_key"
  perms                = "0400"
  error_on_missing_key = true
}

# Online evaluation (Step 37) reads the audit log as audit_reader: read-only, no text in it
template {
  contents             = "{{ with secret \"database/creds/audit-reader\" }}postgresql://{{ .Data.username }}:{{ .Data.password }}@rag-db:5432/audit{{ end }}"
  destination          = "/openbao/out/audit_reader_dsn"
  perms                = "0400"
  error_on_missing_key = true
}
