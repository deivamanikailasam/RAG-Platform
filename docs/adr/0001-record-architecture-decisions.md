# ADR-0001: Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** deivamanikailasam

## Context
The platform will grow to ~15 services and many design choices. Decisions made in chat,
notes or memory are lost, and reviewers/auditors need to know why the system is shaped as it is.

## Decision
We will record every significant decision as a numbered Markdown ADR in docs/adr/, using
0000-template.md. Accepted ADRs are immutable; changes are made by a new ADR that supersedes them.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Wiki / Confluence pages | Easy editing, rich formatting | Drifts from the code, no review in PRs | Separate from the change history |
| Long design docs / RFCs | Deep analysis | Heavy for small decisions | Used later for big designs, alongside ADRs |
| No records | Zero effort | Knowledge loss, repeated debates | Unacceptable for an audited platform |

## Consequences
+ Decisions are reviewed in the same PRs as the code they affect.
+ New contributors can read the reasoning in order.
- Small writing overhead for each significant decision.

## Revisit when
The team adopts a different decision-tracking system with equal traceability.
