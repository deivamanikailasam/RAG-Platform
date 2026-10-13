# RAG platform standards (Step 38)

What every RAG project on this platform does, and how it's checked. **MUST** rules fail
`rag doctor` (and so CI); **SHOULD** rules warn; *reviewed* rules are checked by people at the
production readiness review, with the evidence named here. Change a standard by pull request to
this file and to `rag_core/doctor.py` together.

## Configuration

| Id | Level | Standard | How it's checked |
|---|---|---|---|
| CFG-1 | MUST | One `rag.yaml` with profiles, extending the platform's (`include: {platform: rag-core:platform.yaml}`) | `rag doctor` |
| CFG-2 | MUST | A profile that runs with no services (offline), for tests and CI | `rag doctor` |
| CFG-3 | MUST | A `production` profile | `rag doctor` |
| CFG-4 | MUST | Every profile builds: real component names, valid settings | `rag config validate` |
| CFG-5 | MUST | Production passes readiness: no in-memory stores or stand-in models, no secrets in the file, required guards, checked answers | `rag config readiness` |
| PRM-1 | SHOULD | Answers use a registered, versioned prompt selected by label | `rag doctor`; Step 24 registry |
| CFG-6 | reviewed | Secrets only from files written by OpenBao Agent (`*_file`), never env vars in containers or config | readiness + Step 28 |

## Evaluation

| Id | Level | Standard | How it's checked |
|---|---|---|---|
| EVL-1 | MUST | Labelled questions with the documents that answer them | `rag doctor` |
| EVL-2 | SHOULD | 25+ real user questions, covering every document type and topic | `rag doctor` |
| EVL-3 | MUST | Questions whose answer is not in the documents (honest abstention) | `rag doctor`; `eval-answers --fail-under abstain_ok=1` |
| EVL-4 | MUST | Access-control questions with forbidden documents; zero leaks | `rag doctor`; leaks fail every eval |
| EVL-5 | MUST | Guard cases: attacks AND ordinary questions | `rag doctor`; `rag eval-guards` |
| CI-1..3 | MUST | CI runs search/answer evaluation, guard evaluation and readiness with thresholds | `rag doctor` |
| EVL-6 | reviewed | Online evaluation per release in staging and prod; review queue read weekly | Step 37 `rag online-eval`; runbook |

## Security and privacy

| Id | Level | Standard | Evidence |
|---|---|---|---|
| SEC-1 | reviewed | Every request authenticated (OIDC), authorised by policy, audited before data is returned | Steps 16-18, 23; platform tests |
| SEC-2 | reviewed | Access enforced in every store and re-checked after retrieval | Steps 18, 31; conformance kit |
| SEC-3 | reviewed | Tenants isolated by row-level security (or separate stores) | Step 36 |
| SEC-4 | reviewed | Personal data redacted before indexing; erasure and retention work | Steps 31, 36 |
| SEC-5 | reviewed | Workloads have their own identities and least privilege | Steps 28, 37 |
| SEC-6 | reviewed | Images pinned by digest, signed, scanned; admission policies enforced | Steps 27, 29 |

## Operations

| Id | Level | Standard | Evidence |
|---|---|---|---|
| OPS-1 | reviewed | Promotion through gates; canary releases with analysis | Step 37 `deploy/envs/promotion.yaml` |
| OPS-2 | reviewed | SLOs with burn-rate alerts; answer-quality alerts; runbooks for each | Steps 20, 37 |
| OPS-3 | reviewed | Backups with a restore drill at least monthly; RPO/RTO written down | Steps 36, 37 |
| OPS-4 | reviewed | Model, dataset and system cards current; ADRs for each significant choice | Step 25 |

## Governance

| Id | Level | Standard | How it's checked |
|---|---|---|---|
| GOV-1 | SHOULD | A system card | `rag doctor` |
| GOV-2 | SHOULD | Risk acceptance for what is specific to the project | `rag doctor` |
| GOV-3 | SHOULD | Retention rules (and legal holds) agreed with the records owner | `rag doctor` |
| GOV-4 | SHOULD | Decision records | `rag doctor` |
| GOV-5 | reviewed | Mapping to the frameworks that apply (NIST AI RMF, ISO/IEC 42001, EU AI Act, privacy law) | Step 36 risk register |

## Versioning

- **rag-core follows semantic versioning.** Its public API is: the contracts (`rag_core.contracts`,
  `rag_core.types`), the SDK (`rag_core.sdk`), the CLI, component kind/name/setting names, the
  rag.yaml format and the packaged profiles. A breaking change to any of these is a new MAJOR
  version, announced in `libs/rag-core/CHANGELOG.md` with a migration note.
- Projects pin `rag-core>=1.x,<2` and take template improvements with `copier update`.
