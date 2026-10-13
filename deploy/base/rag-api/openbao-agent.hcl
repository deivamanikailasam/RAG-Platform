# OpenBao Agent inside the rag-api pod (Step 29). Same job as the Compose sidecar (Step 28), but it
# logs in with the pod's Kubernetes service account token instead of an AppRole secret ID:
# nothing to hand over, nothing to renew by hand, and a restarted pod logs in again by itself.
pid_file = ""

vault {
  address = "http://openbao:8200" # the external-deps Service (Compose on your Mac)
}

auto_auth {
  method "jwt" {
    mount_path = "auth/kubernetes-jwt"
    config = {
      role = "rag-api"
      # A short-lived token (10 min) the kubelet writes and refreshes, made for audience "openbao"
      # only: it can't be used against the Kubernetes API or any other service.
      path = "/var/run/secrets/openbao/token"
      remove_jwt_after_reading = false   # the kubelet owns this file and keeps refreshing it
    }
  }
}

template_config {
  exit_on_retry_failure = true
}

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
