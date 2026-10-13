# Documentation map

> **IN PLAIN ENGLISH**
> This folder explains the RAG platform at three depths. The **guides** tell you what to do (set it up,
> ship it, run it, start a project on it). The **architecture and concepts** pages explain how it works
> and why. The **step write-ups, decision records and reference** pages hold every detail, one topic at
> a time. Start with the row for your role below; everything links onward.

## Start here, by role

| You are… | Read first | Then |
|---|---|---|
| **New to the project** | [Architecture overview](architecture/overview.md) (the map) | [RAG handbook](concepts/rag-handbook.md), [glossary](glossary.md) |
| **Setting it up on a Mac** | [Local setup guide](guides/local-setup.md) | [Reference: files and commands](reference.md), [runbooks](runbooks/) |
| **Taking it to production** | [Production promotion guide](guides/production-promotion.md) | [Cloud mapping](architecture/cloud-mapping.md), [ADR-0037](adr/0037-production-environments-canaries-and-recovery.md), [disaster recovery](runbooks/disaster-recovery.md) |
| **Building an assistant on the platform** | [New RAG project guide](guides/new-rag-project.md) | [Standards](standards/rag-standards.md), [catalogue](catalogue.md), [RAG handbook](concepts/rag-handbook.md) |
| **Tuning answer quality** | [RAG handbook](concepts/rag-handbook.md) | [Quality & operations §1](guides/quality-and-operations.md#1-evaluation-and-testing), Steps [31](steps/step-31-ingestion-pipeline.md)–[35](steps/step-35-rag-architectures.md) |
| **On call / operating it** | [Quality & operations §2](guides/quality-and-operations.md#2-observability) | [Runbooks](#runbooks), [local setup: daily use](guides/local-setup.md#daily-use-after-a-restart) |
| **Security, privacy, risk, audit** | [Quality & operations §3–4](guides/quality-and-operations.md#3-security-and-safety) | [Threat model](security/threat-model.md), [controls](compliance/controls.md), [cards](cards/README.md), [SECURITY.md](../SECURITY.md) |
| **Contributing a change** | [CONTRIBUTING.md](../CONTRIBUTING.md) | [ADRs](adr/README.md), [step write-ups](steps/README.md) |
| **Learning from the build guide** | [Step write-ups](steps/README.md) in order | [Glossary](glossary.md), [source PDFs](source/) |

## Guides (what to do)

| Guide | What it covers |
|---|---|
| [Local setup](guides/local-setup.md) | From an empty Apple Silicon Mac to the whole platform: tools, secrets, models, every service in order, Keycloak users, OPA, observability, audit, OpenBao, ingesting the sample corpus, asking questions, CI locally, Kubernetes + Argo CD; ports, troubleshooting, reset, Linux notes |
| [Production promotion](guides/production-promotion.md) | Environments, what changes per environment, CI and signed images, GitOps, promotion gates, canaries and rollback, HA/DR, online evaluation, break glass, the pre-production checklist (placeholders to fill), day-2 operations |
| [Quality and operations](guides/quality-and-operations.md) | Testing and evaluation strategy, observability and SLOs, security and safety, audit log, governance, retention, compliance mapping |
| [New RAG project](guides/new-rag-project.md) | The reuse kit and the template, step by step, from `just new-project` to production |

## How it works and why

| Page | What it covers |
|---|---|
| [Architecture overview](architecture/overview.md) | C4 views, request flows for search and answers, ingestion, data stores, trust boundaries, scaling, failure modes, every ADR in one table |
| [RAG handbook](concepts/rag-handbook.md) | Every RAG technique in plain words, when to use it, and how to switch it in `rag.yaml` |
| [Extensions](extensions/README.md) | Techniques added after the 38 guide steps, one feature group per page: what, why, when to use which, how to switch it on |
| [Cloud mapping](architecture/cloud-mapping.md) | Managed equivalents of every self-run piece on AWS, Google Cloud and Azure |
| [C4 model as code](architecture/workspace.dsl) | Structurizr DSL source of the architecture diagrams |
| [Decision records (ADRs)](adr/README.md) | ADR-0001 to ADR-0039: each decision, its alternatives and when to revisit |
| [Catalogue](catalogue.md) | All 103 switchable components in 25 kinds, with settings and test status (generated) |
| [Standards](standards/rag-standards.md) | The rules every RAG project meets (MUST / SHOULD / reviewed), checked by `rag doctor` |

## Security, compliance and governance

| Page | What it covers |
|---|---|
| [Threat model](security/threat-model.md) | 19 STRIDE + safety threats with controls and residual risk (generated) |
| [Controls and evidence](compliance/controls.md) | 30 controls, their steps, test evidence and framework references (generated) |
| [Risk register](compliance/risk-register.yaml) | The source of both pages above, checked in CI |
| [Access policy](security/access-policy.md) | Who may see and do what (the OPA policy in words) |
| [Gateway access policy](security/gateway-access-policy.md) | Model keys, teams, budgets, limits and their owners |
| [Cards](cards/README.md) | Model, dataset and system cards with the lineage diagram (generated from `cards/`) |
| [Shadow pricing](finops/shadow-pricing.md) | How local model use gets comparable notional prices |
| [Object storage](data/object-storage.md) | Buckets, their rules and who may access them |
| [Model benchmarks](benchmarks/models.md) | Measured time to first token, tokens per second, memory |
| [SECURITY.md](../SECURITY.md) | Reporting vulnerabilities and leaked secrets |

## Runbooks

What to do when an alert fires or something breaks:

| Runbook | For |
|---|---|
| [answer-quality](runbooks/answer-quality.md) | Guard-block, abstention, thumbs-down, latency and failed-job alerts |
| [audit-log](runbooks/audit-log.md) | Audit writes failing, verification failures |
| [canary](runbooks/canary.md) | Canary flow, aborted canaries, manual controls |
| [disaster-recovery](runbooks/disaster-recovery.md) | Every failure from a pod to a region, with RPO and RTO |
| [keycloak-login-failures](runbooks/keycloak-login-failures.md) | Login failure spikes |
| [kubernetes](runbooks/kubernetes.md) | Rollback, OutOfSync/Degraded, sidecar login, pull errors, cluster reset |
| [openbao](runbooks/openbao.md) | Sealed, audit failing, agent login, leaks, break glass |
| [otel-collector-losing-data](runbooks/otel-collector-losing-data.md) | Telemetry being dropped |
| [rag-policy-mismatch](runbooks/rag-policy-mismatch.md) | Query filter and policy disagree |
| [rag-search-errors](runbooks/rag-search-errors.md) | Search error budget burning |
| [rag-search-latency](runbooks/rag-search-latency.md) | Search slower than the SLO |
| [secret-leak](runbooks/secret-leak.md) | A secret has (or might have) leaked |
| [target-down](runbooks/target-down.md) | A scrape target is down |

## The build guide, step by step

The platform was built in 38 steps; each has a full plain-English write-up (goal, analogy, key ideas,
commands, alternatives, common mistakes, what was added to the repository): [steps/README.md](steps/README.md).

| Phase | Steps |
|---|---|
| Workstation | [1 Homebrew](steps/step-01-homebrew-brewfile.md) · [2 uv](steps/step-02-python-uv.md) · [3 containers](steps/step-03-container-runtime.md) · [4 repository and ADRs](steps/step-04-repository-git-adrs.md) · [5 code quality](steps/step-05-linting-formatting-pre-commit.md) · [6 secrets](steps/step-06-local-secrets.md) |
| Models and gateway | [7 mlx-lm](steps/step-07-model-serving-mlx-lm.md) · [8 embeddings and reranker](steps/step-08-embedding-reranker-servers.md) · [9 LiteLLM](steps/step-09-litellm-gateway.md) · [10 budgets and fallbacks](steps/step-10-budgets-rate-limits-fallbacks.md) |
| Data stores | [11 Postgres + pgvector](steps/step-11-postgres-pgvector.md) · [12 Qdrant](steps/step-12-qdrant-vector-database.md) · [13 OpenSearch](steps/step-13-opensearch-keyword-hybrid-search.md) · [14 object storage](steps/step-14-s3-object-storage-seaweedfs.md) · [15 Valkey](steps/step-15-valkey-cache-queues-locks.md) |
| Identity and policy | [16 Keycloak](steps/step-16-keycloak-realm-users-groups.md) · [17 JWT auth](steps/step-17-jwt-auth-on-the-apis.md) · [18 OPA](steps/step-18-policy-engine-opa.md) |
| Observability | [19 OpenTelemetry](steps/step-19-opentelemetry-collector.md) · [20 Prometheus, Grafana, SLOs](steps/step-20-prometheus-grafana-slos-alerts.md) · [21 Loki and Tempo](steps/step-21-loki-tempo-traces-and-logs.md) · [22 Langfuse](steps/step-22-langfuse-llm-traces.md) |
| Governance | [23 audit log](steps/step-23-tamper-evident-audit-log.md) · [24 prompt registry](steps/step-24-prompt-registry.md) · [25 cards and lineage](steps/step-25-cards-and-lineage.md) · [26 evaluation harness](steps/step-26-evaluation-harness.md) |
| Delivery | [27 CI and supply chain](steps/step-27-ci-pipeline-and-supply-chain.md) · [28 OpenBao](steps/step-28-vault-dynamic-secrets.md) · [29 Kubernetes and Argo CD](steps/step-29-kubernetes-gitops-argo-cd.md) |
| RAG core | [30 contracts and components](steps/step-30-rag-core-contracts-and-components.md) · [31 ingestion](steps/step-31-ingestion-pipeline.md) · [32 retrieval and ranking](steps/step-32-retrieval-and-ranking.md) · [33 answers](steps/step-33-augmentation-and-generation.md) · [34 guardrails](steps/step-34-guardrails.md) · [35 architectures](steps/step-35-rag-architectures.md) |
| Production and reuse | [36 lifecycle, threat model, compliance](steps/step-36-lifecycle-threat-model-compliance.md) · [37 environments, canaries, HA/DR](steps/step-37-production-environments-canaries-ha-dr.md) · [38 reuse kit](steps/step-38-reuse-kit-template-sdk-standards.md) |

## Reference

| Page | What it covers |
|---|---|
| [Reference: files and commands](reference.md) | Every file, setting, port, secret name and command (Appendix A) |
| [Glossary](glossary.md) | Every term in plain English, with the step that introduces it (Appendix B) |
| [Coverage audit](coverage-audit.md) | What was checked between the build guide and this repository, and what is created per machine instead of committed |
| [Source build guide (PDF)](source/) | The original guide, in two parts |
| [Changelog](../CHANGELOG.md) | What changed, step by step |
