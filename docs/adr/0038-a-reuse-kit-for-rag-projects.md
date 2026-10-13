# ADR-0038: A reuse kit: versioned rag-core, packaged profiles, standards as code, a project template

- **Status:** Accepted
- **Date:** 2026-10-16
- **Deciders:** <you>

## Context
More RAG projects are coming. Copying the first project would multiply its configuration,
gaps and fixes, and every security review would start from zero.

## Decision
- rag-core 1.0.0 with semantic versioning; its public API is listed in the standards.
- Packaged platform profiles, included and extended by projects' rag.yaml.
- Project components as plugins (entry point or RAG_PLUGINS); contributions back by pull request.
- Standards with ids, checked by `rag doctor` in every project's CI.
- A Copier template, run as an isolated tool; `copier update` for template changes.
- A catalogue generated from the registry.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Copy an example project | Nothing to build | Drift, repeated fixes | No path for improvements |
| Cookiecutter | Popular | No update of existing projects | Copier can update |
| A monorepo for all projects | One version everywhere | Coupled releases, shared CI load | Separate repos on a versioned library |
| Platform-as-a-service only (no code in projects) | Simplest for users | Can't extend; one size fits all | Config + plugins keep extension points |

## Consequences
+ A new project passes every gate on its first run; improvements reach all projects.
- The platform team owns compatibility: breaking changes need a MAJOR version and a migration note.

## Revisit when
Projects need a hosted multi-tenant service rather than their own deployment, or an internal
developer portal becomes the entry point (run this template from it).
