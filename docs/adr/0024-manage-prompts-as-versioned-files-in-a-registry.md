# ADR-0024: Manage prompts as versioned files in a registry

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** deivamanikailasam

## Context
Prompts determine system behaviour as much as code does, but lived as strings in code: unreviewed
as such, not comparable across evaluations, not traceable from a trace or audit event, not quickly
reversible, and easy to write in injection-prone ways.

## Decision
Prompts are files in git: prompts/<name>/v<N>.yaml (schema-validated: kind, owner, gateway model
alias, params, messages or template, declared variables with max length and untrusted flag,
optional evaluation threshold, changelog). Released versions are immutable: prompts.lock.json holds
each file's SHA-256, checked by rag_common.prompts at load, by pre-commit, at service start-up, and
against main ("entries may only be added"). labels.yaml maps environments (production, staging) to
versions; promotion and rollback are label PRs, owned via CODEOWNERS. Untrusted variables may not
appear in system messages, must sit alone inside a tag, have their closing tag neutralised, and are
length-capped; rendering is single-pass; YAML is read with safe_load. The registry is baked into the
rag-api image; RAG_API_PROMPT_LABEL selects the label; start-up fails on any registry error or a
missing required prompt. Prompt refs (name@version) are recorded in Langfuse metadata, audit details
and the rag_prompt_info info metric, with Grafana annotations on version changes.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Strings in code | Simple | No review/traceability/rollback | The problem we're solving |
| Langfuse prompt management | UI, labels, links generations to prompts, runtime fetch | Changes can bypass git review and CI; runtime dependency | Revisit for non-engineer editing; could be fed from git |
| MLflow / LangSmith prompt registries | Rich tooling | Another platform; tied to their ecosystems | Not otherwise used here |
| Runtime-fetched prompts (hot reload) | Change without deploy | Unreviewed changes reach production; harder audit | Speed isn't worth losing the gate here |

## Consequences
+ Every behaviour-relevant prompt change is reviewed, frozen, attributable and reversible.
+ Evaluation results, traces and audit events point at exact prompt text.
- Changing a prompt in production needs a build and deploy (minutes, not seconds).
- Non-engineers edit YAML in pull requests; a UI may be needed later.

## Revisit when
Many people outside engineering author prompts, prompts must change faster than deploys allow,
or the evaluation harness (Step 26) is ready to gate production labels automatically.
