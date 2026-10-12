# Architecture Decision Records

| ADR | Title | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-workstation-tools-via-homebrew-brewfile.md) | Workstation tools via Homebrew + Brewfile | Accepted |
| [0003](0003-python-312-managed-by-uv.md) | Python 3.12 managed by uv, committed lockfile | Accepted |
| [0004](0004-orbstack-native-models-containerised-services.md) | Native models, containerised services (OrbStack) | Accepted |
| [0005](0005-automated-code-quality-gates-with-ruff-mypy-pytest-and-pre-commit.md) | Automated code quality gates with ruff, mypy, pytest and pre-commit | Accepted |
| [0006](0006-manage-dev-secrets-with-sops-and-age-personal-tokens-in-keychain.md) | Manage dev secrets with SOPS + age; personal tokens in the macOS Keychain | Accepted |
| [0007](0007-serve-local-models-natively-with-mlx-lm-behind-localhost.md) | Serve local models natively with mlx-lm, bound to localhost | Accepted |
| [0008](0008-serve-embeddings-and-reranking-with-tei-natively-behind-an-api-key.md) | Serve embeddings and reranking with TEI natively, behind an API key | Accepted |
| [0009](0009-route-all-model-access-through-a-litellm-gateway.md) | Route all model access through a LiteLLM gateway | Accepted |
| [0010](0010-govern-model-access-with-virtual-keys-budgets-shadow-prices-and-fallbacks.md) | Govern model access with virtual keys, budgets, shadow prices and fallbacks | Accepted |
| [0011](0011-use-postgres-with-pgvector-as-the-primary-document-and-vector-store.md) | Use Postgres with pgvector as the primary document and vector store | Accepted |
| [0012](0012-use-qdrant-as-a-derived-vector-index-alongside-postgres.md) | Use Qdrant as a derived vector index alongside Postgres | Accepted |
| [0013](0013-use-opensearch-for-keyword-and-hybrid-search-as-a-derived-index.md) | Use OpenSearch for keyword and hybrid search as a derived index | Accepted |
| [0014](0014-use-seaweedfs-as-the-s3-compatible-object-store-instead-of-minio.md) | Use SeaweedFS as the S3-compatible object store instead of MinIO | Accepted |
| [0015](0015-use-valkey-for-cache-queues-and-locks.md) | Use Valkey for cache, queues and locks | Accepted |
| [0016](0016-use-keycloak-for-identity.md) | Use Keycloak for identity | Accepted |
| [0017](0017-validate-jwts-locally-in-every-service.md) | Validate JWTs locally in every service | Accepted |
| [0018](0018-use-opa-as-the-policy-decision-point.md) | Use OPA as the policy decision point | Accepted |

New ADR: `just adr "Short title"`, then fill it in and add a row here.
