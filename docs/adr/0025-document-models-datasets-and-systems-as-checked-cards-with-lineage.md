# ADR-0025: Document models, datasets and systems as checked cards with lineage

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** deivamanikailasam

## Context
We run four models, several datasets with personal data, and one AI system. Questions about use,
licences, personal data and the impact of changes had no single, current answer. Facts about
models were already recorded in models.yaml, the gateway config and the prompt registry.

## Decision
YAML cards in cards/{models,datasets,systems}/ with strict schemas (owner, status, summary,
inputs, limitations, review interval, approvals; model: task, licence with verified date,
intended/out-of-scope use, risks, training data, data handling, fallback_allowed, evaluation;
dataset: role, locations, provenance, classification, personal data + legal basis, retention,
deletion, access; system: purpose, users, intended/out-of-scope use, human oversight, risk
assessment). cards/policy.yaml lists allowed SPDX licences. rag_common.cards cross-checks cards
with models.yaml, the LiteLLM config and the prompt registry (never copying their facts), builds
a lineage DAG from card inputs, prompt->model links and gateway fallbacks, and answers impact
and lineage queries. Errors fail pre-commit/CI; time-based warnings fail a weekly strict run.
Readable pages and a Mermaid lineage diagram are generated into docs/cards/ and checked.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Wiki pages | Easy to write | Not checked; drift; no lineage | Rot silently |
| Hugging Face-style README cards | Familiar format | Free text; hard to check | Kept as generated output instead |
| Data catalogue (DataHub, OpenMetadata) + OpenLineage | Runtime lineage, search, UI | Heavy services to run | Revisit with many pipelines/teams |
| CycloneDX ML-BOM / SPDX 3 AI | Standard, machine-readable | Inventory only; little on use and limits | Export later with Step 27's SBOMs |

## Consequences
+ One place to answer use, licence, personal-data and impact questions; checked on every change.
+ Configuration mistakes (unreviewed models, forbidden fallbacks) fail the build.
- Cards must be maintained; reviews are due regularly.
- Lineage is declared, not observed; a pipeline that isn't declared won't appear.

## Revisit when
Pipelines multiply (Step 36: emit OpenLineage events), an organisation-wide catalogue exists,
or a regulator or customer asks for a standard format (CycloneDX ML-BOM, SPDX 3).
