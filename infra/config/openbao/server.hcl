# OpenBao server (Step 28). One node, integrated (raft) storage on a Docker volume.
storage "raft" {
  path    = "/openbao/file" # the image's data folder (owned by its openbao user)
  node_id = "bao-1"
}

# Plain HTTP ONLY because the listener is reachable on the internal Docker network and on
# 127.0.0.1 of your Mac. Anywhere else: TLS (tls_cert_file / tls_key_file), no exceptions.
listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true
  telemetry {
    unauthenticated_metrics_access = true # Prometheus reads /v1/sys/metrics: counts, never secrets
  }
}

api_addr     = "http://openbao:8200"
cluster_addr = "http://openbao:8201"

# mlock would pin memory so secrets never reach swap. The OpenBao docs recommend switching it
# off with raft storage: raft memory-maps its database file, and mlock would pin all of it.
# The trade-off: memory could in principle be swapped to disk. On a Mac, the Docker VM's disk
# lives on your drive, so keep FileVault on.
disable_mlock = true
ui            = false
log_level     = "info"

# Metrics in Prometheus format (scraped by Step 20's Prometheus)
telemetry {
  prometheus_retention_time = "24h"
  disable_hostname          = true
}

# The audit device is declared here, not created through the API (OpenBao 2.x refuses that, so
# a stolen admin token can't quietly add or redirect an audit log). Every request and response
# is written as one JSON line; secret values are HMAC'd, never in clear text. If NO audit device
# can write, OpenBao refuses requests: an unrecorded secret is never handed out.
audit "file" "file" {
  description = "Every request and response; secret values HMAC'd"
  options {
    file_path = "/openbao/logs/audit.log"
    mode      = "0600"
  }
}
