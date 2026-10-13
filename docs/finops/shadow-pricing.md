# Shadow pricing for local models

Purpose: make GPU usage visible, comparable and budgetable. These are NOT real bills.

- Notional GPU rate: $2.00 per hour (review yearly; record changes here and in an ADR)
- price_out = rate / (3600 × decode tok/s)              price_in = rate / (3600 × prefill tok/s)
- Source of tok/s: docs/benchmarks/models.md (re-price after major model or mlx-lm changes)

| Model role | decode tok/s | prefill tok/s | output $/token | input $/token |
|---|---|---|---|---|
| qwen-quality | 20 | 200 | 0.0000278 | 0.0000028 |
| qwen-fast | 80 | 800 | 0.0000069 | 0.0000007 |
| embedder | n/a | ~28,000 | 0 | 0.00000002 |
| reranker | n/a | n/a | 0 (budget checks skipped) | 0 |

> **Starting values, not measurements yet.** The rows above use the guide's worked example (27B decodes at
> ~20 tok/s, the fast MoE at ~80 tok/s, prefill roughly 10× decode) so that `infra/config/litellm/config.yaml`
> carries non-zero prices from day one and budgets work. Replace them with your own numbers from
> `docs/benchmarks/models.md` (`just bench`, `just bench-embed`), then copy the new prices into the config's
> `model_info` in the same pull request.

## How to re-derive a price

```bash
# rate in $/hour, then tokens per second from the benchmark table
python3 -c 'rate=2.00; tps=20; print(f"{rate / (3600 * tps):.7f}")'     # -> 0.0000278 per token
```

1. Run the benchmarks (Step 7 / Step 8) and record decode tok/s and prefill tok/s.
2. Compute both prices with the formula; round to 2 significant figures.
3. Update this table and `model_info.input_cost_per_token` / `output_cost_per_token` in the gateway config.
4. Restart the gateway (`just up`) and note the change in the PR description. A change to the hourly rate itself
   needs an ADR, because it changes every team's reported spend.

## Why the reranker is left at zero

LiteLLM prices rerank calls per search unit, not per token, and skips budget checks for zero-cost models. Reranking
is short and bounded (one query, at most ~50 candidates), so it is not where GPU time goes; it is left at zero
rather than invent a per-call number. If reranking volume grows, give it a per-call shadow price derived the same
way (rate ÷ calls per hour from `just bench-embed`).
