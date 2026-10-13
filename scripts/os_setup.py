#!/usr/bin/env python3
"""Create least-privilege users, the versioned chunks index (analyzers, synonyms, k-NN) and the hybrid pipeline.

Run: just with-secrets uv run --with opensearch-py scripts/os_setup.py
"""

import os

from opensearchpy import OpenSearch

INDEX, ALIAS = "rag-chunks-v1", "rag-chunks"
SEC = "/_plugins/_security/api"

admin = OpenSearch(
    hosts=[{"host": "127.0.0.1", "port": 9200}],
    use_ssl=True,
    verify_certs=False,
    ssl_show_warn=False,
    http_auth=("admin", os.environ["OPENSEARCH_ADMIN_PASSWORD"]),
)
req = admin.transport.perform_request

# --- least-privilege roles and users ---
roles = {
    "rag_search": {
        "cluster_permissions": ["cluster_composite_ops_ro"],
        "index_permissions": [{"index_patterns": ["rag-chunks*"], "allowed_actions": ["read"]}],
    },
    "rag_indexer": {
        "cluster_permissions": ["cluster_composite_ops"],
        "index_permissions": [
            {
                "index_patterns": ["rag-chunks*"],
                "allowed_actions": ["crud", "create_index", "manage_aliases"],
            }
        ],
    },
}
passwords = {
    "rag_search": os.environ["OPENSEARCH_SEARCH_PASSWORD"],
    "rag_indexer": os.environ["OPENSEARCH_INDEXER_PASSWORD"],
}
for name, body in roles.items():
    req("PUT", f"{SEC}/roles/{name}", body=body)
    req("PUT", f"{SEC}/internalusers/{name}", body={"password": passwords[name]})
    req("PUT", f"{SEC}/rolesmapping/{name}", body={"users": [name]})
print("users: rag_search (read), rag_indexer (write) on rag-chunks*")

# --- the index: analyzers + synonyms + keyword filters + k-NN vector field ---
if not admin.indices.exists(index=INDEX):
    admin.indices.create(
        index=INDEX,
        body={
            "settings": {
                "index": {"knn": True, "number_of_shards": 1, "number_of_replicas": 0},
                "analysis": {
                    "filter": {
                        "rag_synonyms": {
                            "type": "synonym_graph",
                            "synonyms": [
                                "wfh, work from home, remote work",
                                "pto, paid time off, annual leave",
                            ],
                        },
                        "english_stemmer": {"type": "stemmer", "language": "english"},
                    },
                    "analyzer": {
                        "rag_index": {
                            "tokenizer": "standard",
                            "filter": ["lowercase", "english_stemmer"],
                        },
                        "rag_query": {
                            "tokenizer": "standard",
                            "filter": ["lowercase", "rag_synonyms", "english_stemmer"],
                        },
                    },
                },
            },
            "mappings": {
                "properties": {
                    "text": {
                        "type": "text",
                        "analyzer": "rag_index",
                        "search_analyzer": "rag_query",
                    },
                    "title": {
                        "type": "text",
                        "analyzer": "rag_index",
                        "search_analyzer": "rag_query",
                        "fields": {"raw": {"type": "keyword"}},
                    },
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": 1024,
                        "method": {
                            "name": "hnsw",
                            "engine": "lucene",
                            "space_type": "cosinesimil",
                            "parameters": {"m": 16, "ef_construction": 100},
                        },
                    },
                    "tenant_id": {"type": "keyword"},
                    "acl_groups": {"type": "keyword"},
                    "classification": {"type": "keyword"},
                    "document_id": {"type": "long"},
                    "source_uri": {"type": "keyword"},
                }
            },
            "aliases": {ALIAS: {}},
        },
    )
    print("created", INDEX, "with alias", ALIAS)

# --- hybrid search pipeline: min-max normalise each score list, then weighted mean ---
req(
    "PUT",
    "/_search/pipeline/rag-hybrid",
    body={
        "description": "Normalise BM25 and k-NN scores to 0-1, then 0.3*keyword + 0.7*vector",
        "phase_results_processors": [
            {
                "normalization-processor": {
                    "normalization": {"technique": "min_max"},
                    "combination": {
                        "technique": "arithmetic_mean",
                        "parameters": {"weights": [0.3, 0.7]},
                    },
                }
            }
        ],
    },
)
print("pipeline rag-hybrid ready")
