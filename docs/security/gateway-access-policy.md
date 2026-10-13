# Gateway access policy (dev environment)

| Team | Budget | Period | Key alias | Allowed models | RPM | Max parallel | Expires | Owner |
|---|---|---|---|---|---|---|---|---|
| rag-apps | $50 | 30d | rag-api-dev | qwen-quality, qwen-fast, embedder, reranker | 60 | 4 | 90d | deivamanikailasam |
| rag-apps | (team) | | ingestion-dev | embedder, qwen-fast | 600 | 8 | 90d | deivamanikailasam |
| evaluation | $200 | 30d | eval-harness | qwen-quality, qwen-fast, embedder, reranker | 120 | 4 | 90d | deivamanikailasam |

Rules
- Master key: admin tasks only, never in application config.
- One key per application per environment; keys expire and are re-issued, not extended forever.
- New keys or wider access require a PR updating this file.
- Quarterly review: block unused keys, check spend against budgets.

## How the table is applied

Teams and keys are created from this table with the admin tool (master key, decrypted only in memory):

```bash
just gateway-admin team rag-apps   --budget 50  --models qwen-quality qwen-fast embedder reranker
just gateway-admin team evaluation --budget 200 --models qwen-quality qwen-fast embedder reranker
# copy each printed team_id into the commands below

just gateway-admin key rag-api-dev   --team-id <rag-apps-id>   --models qwen-quality qwen-fast embedder reranker --rpm 60  --parallel 4
just gateway-admin key ingestion-dev --team-id <rag-apps-id>   --models embedder qwen-fast                      --rpm 600 --parallel 8
just gateway-admin key eval-harness  --team-id <evaluation-id> --models qwen-quality qwen-fast embedder reranker --rpm 120 --parallel 4

just secrets-edit    # store each printed key: RAG_API_GATEWAY_KEY=…  INGESTION_GATEWAY_KEY=…  EVAL_GATEWAY_KEY=…
```

Keys are shown once (LiteLLM stores only a hash). A lost or leaked key is blocked
(`just gateway-admin block <key>`) and re-issued, never recovered. `just gateway-test` proves that the
allow-list, rate limit and budget controls reject requests.
