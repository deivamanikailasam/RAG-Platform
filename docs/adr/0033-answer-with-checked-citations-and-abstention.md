# ADR-0033: Answer from numbered sources, check citations, abstain rather than guess

- **Status:** Accepted
- **Date:** 2026-10-13
- **Deciders:** deivamanikailasam

## Context
Generated answers must be traceable to permitted documents, must not invent facts, must handle
follow-ups, must feel fast, and must be recorded without storing personal text.

## Decision
rag-core's AnswerPipeline: memory (per person + session, TTL) → input guards → cache (key: access
fingerprint, normalised question, conversation, settings, prompt, model, index epoch) → Step 32
search + the service's post-check (OPA) → abstain with no model call if nothing is found →
numbered `<doc id="n">` context within a token budget → the registered answer prompt on the
answer model (streamed or whole) → keep only citations to shown documents; flag uncited answers
→ output guards → remember and cache. rag-api serves /v1/answer (JSON or SSE) and /v1/feedback;
the audit event (document ids, prompt, model, outcome, tokens; never text) is written before any
text leaves the service.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Trust the model's citations | Simple | Cites documents it never saw | Check against the context |
| Always call the model, even with no hits | Simpler flow | Pays to invent an answer | Abstain early |
| Answer caches keyed by question only | More hits | Leaks answers across permission sets | Access fingerprint in the key |
| Semantic cache by default | More hits | Near-identical questions with different answers | Opt-in, high threshold |
| WebSockets for streaming | Two-way | Harder through proxies and gateways | Server-sent events |
| Store questions and answers in the audit log | Full replay | Personal data in a long-lived log | Ids, counts, versions only; Langfuse (masked) for debugging |

## Consequences
+ Every answer is attributable, every refusal is honest, repeats are cheap, and nothing is handed
  out unrecorded.
- Citation quality depends on the model following the prompt; uncited answers need a product
  decision (flag or abstain).
- Memory holds personal questions for its TTL; retention must be declared (Step 36).

## Revisit when
Models offer native, verifiable citation APIs; answers need cross-document reasoning beyond one
pass (Step 35's agentic patterns); or product needs long-term per-user memory.
