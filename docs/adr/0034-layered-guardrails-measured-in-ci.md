# ADR-0034: Layered, switchable guardrails at three stages, measured in CI

- **Status:** Accepted
- **Date:** 2026-10-13
- **Deciders:** deivamanikailasam

## Context
Questions and retrieved documents are untrusted text. Prompt injection (direct and indirect),
personal data, secrets, out-of-scope advice and unsupported answers are known risks that reviewers
expect named, controlled, tested and monitored controls for.

## Decision
Guards are rag-core components at three stages (input, context, output) returning allow, flag,
redact or block. Default offline set: size, injection, pii (input), topics, context-injection,
groundedness (flag), pii (output), secrets, toxicity. Model-based (llm-judge) and external
(webhook) guards are available and fail open by default. People see a fixed message when blocked;
reasons go to the trace, the audit log and a metric. `stream: checked` is available where unchecked
text must never leave. `rag eval-guards` measures catch rate and false positive rate, lists known
gaps, and gates CI (≥ 0.95 caught, ≤ 0.05 false positives).

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Rely on the model's own safety training | Nothing to build | Not configurable, not measurable, varies by model | Layered guards |
| One framework (NeMo Guardrails, Guardrails AI) for everything | Rich features | Another runtime and DSL; harder to test per check | Webhook adapter lets one plug in |
| Model-based checks only | Catches rephrasing | Cost and latency per request; can itself be fooled | Patterns first, judge optional |
| Block on every flag | Simple | Many false positives, frustrated users | Per-guard actions, measured |

## Consequences
+ Named, tested controls for each risk; evidence for reviewers in CI.
- Pattern guards miss rephrased attacks (documented as known gaps); lists need maintenance.
- Live streaming can show unchecked text briefly; checked mode trades latency for that.

## Revisit when
A model-based guard is affordable per request, attack monitoring (Step 37) shows new patterns, or a
company-wide guard service exists (use the webhook guard).
