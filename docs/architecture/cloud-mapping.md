# Cloud service mapping (Step 37)

Every piece the platform runs itself has a managed equivalent with the same interface. Swapping one
in changes **where a name points** (deploy/components/managed-deps), not rag-api's settings. What to
keep in mind for each:

| Platform piece (local) | Kubernetes, self-run | AWS | Google Cloud | Azure | Keep in mind |
|---|---|---|---|---|---|
| Kubernetes (OrbStack) | any conformant cluster | EKS | GKE | AKS | Kubernetes 1.33+ for native sidecars; ValidatingAdmissionPolicy GA in 1.30 |
| Postgres + pgvector (Compose) | CloudNativePG (deploy/data) | RDS / Aurora PostgreSQL | Cloud SQL / AlloyDB | Azure Database for PostgreSQL Flexible | pgvector version and HNSW support; row-level security works everywhere |
| Qdrant | Qdrant Helm chart | Qdrant Cloud on AWS | Qdrant Cloud on GCP | Qdrant Cloud on Azure | the vector-store conformance kit (Step 31) decides |
| OpenSearch | OpenSearch operator | Amazon OpenSearch Service | Elastic Cloud | Elastic Cloud / Azure AI Search* | *a different API: needs its own adapter + conformance run |
| MinIO / SeaweedFS (originals) | MinIO / Ceph | S3 (Object Lock) | Cloud Storage (bucket lock) | Blob Storage (immutable storage) | versioning + retention lock = erasure must delete versions (Step 36) |
| Valkey | Valkey Helm chart | ElastiCache for Valkey | Memorystore for Valkey | Azure Cache for Redis | ACLs and TLS on; it holds conversations: same retention rules |
| Keycloak | Keycloak operator | Cognito / your IdP | Identity Platform / your IdP | Entra ID | only the issuer, audience and group claims matter to rag-api |
| OpenBao | OpenBao Helm chart | Secrets Manager + IAM | Secret Manager + Workload Identity | Key Vault + Workload Identity | dynamic DB credentials are OpenBao's; managed stores rotate on a schedule instead |
| OPA | OPA sidecar / service | same | same | same | policies are code: no managed equivalent needed |
| LiteLLM gateway | LiteLLM Deployment | + Bedrock as a provider | + Vertex AI as a provider | + Azure OpenAI as a provider | budgets, keys and audit stay in the gateway (Step 10) |
| Models (MLX on the Mac) | vLLM / TGI on GPU nodes | Bedrock / SageMaker | Vertex AI | Azure OpenAI / AI Foundry | data residency and no-training terms in the contract |
| Embeddings / reranker (TEI) | TEI on CPU/GPU nodes | Bedrock (Titan, Cohere) | Vertex embeddings | Azure OpenAI embeddings | changing the embedder = `rag reindex` (Step 36) |
| Prometheus / Grafana | kube-prometheus-stack | Managed Prometheus + Managed Grafana | Managed Service for Prometheus | Monitor managed Prometheus + Managed Grafana | OTLP in; keep the alert rules and their tests |
| Tempo / Loki | Grafana Tempo / Loki | X-Ray / CloudWatch Logs | Cloud Trace / Cloud Logging | Application Insights / Log Analytics | no question or answer text in logs or spans (Step 21) |
| Langfuse | Langfuse Helm chart | same | same | same | holds prompts and answers: its own retention (Step 22) |
| Argo CD + Rollouts | Argo CD + Argo Rollouts | same (or Flux + Flagger) | same | same | git stays the source of truth |
| Object Lock audit archive | MinIO lock | S3 Object Lock | bucket lock | immutable blob storage | WORM retention per your records schedule |

**Data residency applies to backups too:** a cross-region copy (deploy/data ObjectStore) needs the
same legal basis as the original.

**How to switch one piece.** Point its Service in deploy/components/managed-deps/services.yaml at the
managed endpoint (an `ExternalName`), give rag-api and the worker credentials through OpenBao or the
cloud's workload identity, and run the conformance and evaluation gates against it before promoting
(`just gates staging sha256:…`).
