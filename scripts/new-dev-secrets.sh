#!/usr/bin/env bash
# Generate fresh random dev secrets and store them ENCRYPTED in secrets/dev.enc.env.
set -euo pipefail
out="secrets/dev.enc.env"
if [ -e "$out" ]; then echo "$out already exists. Edit it with: sops $out"; exit 1; fi
mkdir -p secrets
umask 077                                    # new files readable by you only
# If anything fails before encryption finishes, delete the plaintext file.
trap 'grep -q "^sops_mac=" "$out" 2>/dev/null || rm -f "$out"' EXIT

rand() { openssl rand -base64 48 | tr -d '/+=\n' | cut -c1-32; }   # 32 random letters/digits
ospw() { echo "$(openssl rand -base64 24 | tr -d '/+=\n')#9Qx"; }   # OpenSearch password policy: all 4 character classes

cat > "$out" <<EOF
# --- Data stores (Steps 11-15) ---
POSTGRES_PASSWORD=$(rand)
# --- rag-db roles (Step 11): letters/digits only, safe inside a database URL ---
RAG_DB_MIGRATOR_PASSWORD=$(rand)
RAG_DB_APP_PASSWORD=$(rand)
RAG_DB_READONLY_PASSWORD=$(rand)
# --- Qdrant (Step 12): admin key (also signs JWTs) and read-only key ---
QDRANT_API_KEY=$(openssl rand -hex 32)
QDRANT_READ_ONLY_API_KEY=$(openssl rand -hex 32)
# --- OpenSearch (Step 13): strong passwords (upper, lower, digit, symbol) or OpenSearch refuses them ---
OPENSEARCH_ADMIN_PASSWORD=$(ospw)
OPENSEARCH_SEARCH_PASSWORD=$(ospw)
OPENSEARCH_INDEXER_PASSWORD=$(ospw)
MINIO_ROOT_USER=rag-admin
MINIO_ROOT_PASSWORD=$(rand)
REDIS_PASSWORD=$(rand)
# --- Identity (Step 16) ---
KEYCLOAK_ADMIN_PASSWORD=$(rand)
# --- Gateway (Step 9): LiteLLM master keys must start with sk- ---
LITELLM_MASTER_KEY=sk-$(rand)
# --- Gateway database and salt key (Step 10). The salt key encrypts what LiteLLM stores: NEVER rotate it casually ---
LITELLM_DB_PASSWORD=$(rand)
LITELLM_SALT_KEY=$(openssl rand -hex 32)
# --- Embedding and reranker servers (Step 8): TEI API key ---
TEI_API_KEY=$(openssl rand -hex 24)
# --- Observability (Steps 20, 22) ---
GRAFANA_ADMIN_PASSWORD=$(rand)
LANGFUSE_SALT=$(rand)
LANGFUSE_NEXTAUTH_SECRET=$(rand)
LANGFUSE_ENCRYPTION_KEY=$(openssl rand -hex 32)
# --- Demo value used in this step ---
DEMO_TOKEN=$(rand)
EOF

sops --encrypt --in-place "$out"
echo "created $out (encrypted). View names with: just secrets-keys"
