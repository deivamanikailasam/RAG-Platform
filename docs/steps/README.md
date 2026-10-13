# Step-by-step build notes

One write-up per chapter of the *Project 0 · RAG Platform Foundation* build guide
(source PDFs in [`docs/source/`](../source/)). Each write-up follows the guide's section pattern
(At a glance → The big idea → … → Recap) and ends with the files that step added to this repository.

The guide's project folder `~/dev/rag-platform/` is the root of this repository.

Phases: **A** Workstation · **B** Model serving · **C** Data stores · **D** Identity & policy ·
**E** Observability · **F** Audit & governance · **G** Quality & delivery · **H** RAG core ·
**I** Production & reuse.

| Step | Title | Phase | Write-up |
|---:|---|---|---|
| 1 | Homebrew and the Brewfile | A · Workstation | [step-01-homebrew-brewfile.md](step-01-homebrew-brewfile.md) |
| 2 | Python toolchain with uv | A · Workstation | [step-02-python-uv.md](step-02-python-uv.md) |
| 3 | Container runtime: native models, containerised services | A · Workstation | [step-03-container-runtime.md](step-03-container-runtime.md) |
| 4 | Repository, git conventions and your first ADRs | A · Workstation | [step-04-repository-git-adrs.md](step-04-repository-git-adrs.md) |
| 5 | Linting, formatting and pre-commit hooks | A · Workstation | [step-05-linting-formatting-pre-commit.md](step-05-linting-formatting-pre-commit.md) |
| 6 | Local secrets handling | A · Workstation | [step-06-local-secrets.md](step-06-local-secrets.md) |
| 7 | Serving both Qwen models with mlx-lm | B · Model serving | [step-07-model-serving-mlx-lm.md](step-07-model-serving-mlx-lm.md) |
| 8 | Embedding and reranker servers | B · Model serving | [step-08-embedding-reranker-servers.md](step-08-embedding-reranker-servers.md) |
| 9 | The LiteLLM gateway: one front door for every model | B · Model serving | [step-09-litellm-gateway.md](step-09-litellm-gateway.md) |
| 10 | Budgets, rate limits and fallbacks | B · Model serving | [step-10-budgets-rate-limits-fallbacks.md](step-10-budgets-rate-limits-fallbacks.md) |
| 11 | Postgres + pgvector: the document and vector store | C · Data stores | [step-11-postgres-pgvector.md](step-11-postgres-pgvector.md) |
| 12 | Qdrant: a dedicated vector database | C · Data stores | [step-12-qdrant-vector-database.md](step-12-qdrant-vector-database.md) |
| 13 | OpenSearch: keyword, analyzers and hybrid search | C · Data stores | [step-13-opensearch-keyword-hybrid-search.md](step-13-opensearch-keyword-hybrid-search.md) |
| 14 | S3 object storage for original files (SeaweedFS) | C · Data stores | [step-14-s3-object-storage-seaweedfs.md](step-14-s3-object-storage-seaweedfs.md) |
| 15 | Valkey (Redis-compatible): cache, queues and locks | C · Data stores | [step-15-valkey-cache-queues-locks.md](step-15-valkey-cache-queues-locks.md) |
| 16 | Keycloak: realm, users and groups | D · Identity & policy | [step-16-keycloak-realm-users-groups.md](step-16-keycloak-realm-users-groups.md) |
| 17 | JWT auth on the APIs | D · Identity & policy | [step-17-jwt-auth-on-the-apis.md](step-17-jwt-auth-on-the-apis.md) |
| 18 | Policy engine: OPA (with OpenFGA in view) | D · Identity & policy | [step-18-policy-engine-opa.md](step-18-policy-engine-opa.md) |
| 19 | OpenTelemetry Collector: one pipe for traces, metrics and logs | E · Observability | [step-19-opentelemetry-collector.md](step-19-opentelemetry-collector.md) |
| 20 | Prometheus + Grafana: dashboards, SLOs and alerts | E · Observability | [step-20-prometheus-grafana-slos-alerts.md](step-20-prometheus-grafana-slos-alerts.md) |
| 21 | Loki + Tempo: from a spike to the exact trace and log line | E · Observability | [step-21-loki-tempo-traces-and-logs.md](step-21-loki-tempo-traces-and-logs.md) |
| 22 | Langfuse: LLM traces with content, under control | E · Observability | [step-22-langfuse-llm-traces.md](step-22-langfuse-llm-traces.md) |
| 23 | A tamper-evident audit log | F · Audit & governance | [step-23-tamper-evident-audit-log.md](step-23-tamper-evident-audit-log.md) |
| 24 | A prompt registry | F · Audit & governance | [step-24-prompt-registry.md](step-24-prompt-registry.md) |
| 25 | Model, dataset and system cards, and lineage | F · Audit & governance | [step-25-cards-and-lineage.md](step-25-cards-and-lineage.md) |
| 26 | An evaluation harness | G · Quality & delivery | [step-26-evaluation-harness.md](step-26-evaluation-harness.md) |
| 27 | A CI pipeline and a secured supply chain | G · Quality & delivery | [step-27-ci-pipeline-and-supply-chain.md](step-27-ci-pipeline-and-supply-chain.md) |
| 28 | Vault: secrets issued on demand, short-lived and audited | G · Quality & delivery | [step-28-vault-dynamic-secrets.md](step-28-vault-dynamic-secrets.md) |
| 29 | Kubernetes and GitOps with Argo CD | G · Quality & delivery | [step-29-kubernetes-gitops-argo-cd.md](step-29-kubernetes-gitops-argo-cd.md) |
