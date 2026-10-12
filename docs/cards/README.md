# Cards: models, datasets and systems

<!-- generated from cards/ by `just cards docs`: do not edit -->

| Card | Title | Status | Owner | Last reviewed |
|---|---|---|---|---|
| [dataset:audit-log](dataset-audit-log.md) | Audit log (who received what) | approved | security | 2026-10-12 |
| [dataset:company-chunks](dataset-company-chunks.md) | Company document chunks and vectors (the search indexes) | approved | rag-platform | 2026-10-12 |
| [dataset:company-documents](dataset-company-documents.md) | Company documents (the source corpus) | approved | knowledge-management | 2026-10-12 |
| [dataset:llm-traces](dataset-llm-traces.md) | LLM traces in Langfuse | approved | rag-platform | 2026-10-12 |
| [dataset:rag-answer-golden](dataset-rag-answer-golden.md) | Golden questions and answers for rag-answer | approved | rag-quality | 2026-10-12 |
| [dataset:retrieval-golden](dataset-retrieval-golden.md) | Golden retrieval cases per persona | approved | rag-quality | 2026-10-12 |
| [model:embedder](model-embedder.md) | Qwen3-Embedding-0.6B (embedder) | approved | rag-platform | 2026-10-12 |
| [model:qwen-fast](model-qwen-fast.md) | Qwen3.6-35B-A3B, 4-bit MLX (qwen-fast) | approved | rag-platform | 2026-10-12 |
| [model:qwen-quality](model-qwen-quality.md) | Qwen3.8-27B, 8-bit MLX (qwen-quality) | approved | rag-platform | 2026-10-12 |
| [model:reranker](model-reranker.md) | bge-reranker-v2-m3 (reranker) | approved | rag-platform | 2026-10-12 |
| [system:rag-api](system-rag-api.md) | rag-api (the company knowledge search service) | approved | rag-platform | 2026-10-12 |

## Lineage

```mermaid
flowchart LR
    dataset_audit_log[("dataset:audit-log")]
    dataset_company_chunks[("dataset:company-chunks")]
    dataset_company_documents[("dataset:company-documents")]
    dataset_llm_traces[("dataset:llm-traces")]
    dataset_rag_answer_golden[("dataset:rag-answer-golden")]
    dataset_retrieval_golden[("dataset:retrieval-golden")]
    model_embedder(["model:embedder"])
    model_qwen_fast(["model:qwen-fast"])
    model_qwen_quality(["model:qwen-quality"])
    model_reranker(["model:reranker"])
    prompt_eval_judge[/"prompt:eval-judge"/]
    prompt_query_instruction[/"prompt:query-instruction"/]
    prompt_rag_answer[/"prompt:rag-answer"/]
    system_rag_api[["system:rag-api"]]
    dataset_company_chunks --> system_rag_api
    dataset_company_documents --> dataset_company_chunks
    dataset_company_documents --> dataset_rag_answer_golden
    dataset_company_documents --> dataset_retrieval_golden
    model_embedder --> dataset_company_chunks
    model_embedder --> prompt_query_instruction
    model_embedder --> system_rag_api
    model_qwen_fast -.->|fallback| prompt_eval_judge
    model_qwen_fast -.->|fallback| prompt_rag_answer
    model_qwen_quality --> prompt_eval_judge
    model_qwen_quality --> prompt_rag_answer
    prompt_query_instruction --> system_rag_api
    system_rag_api --> dataset_audit_log
    system_rag_api --> dataset_llm_traces
```
