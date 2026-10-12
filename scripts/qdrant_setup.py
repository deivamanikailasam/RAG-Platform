#!/usr/bin/env python3
"""Create the versioned chunks collection, its payload indexes and the stable alias.

Run: just with-secrets uv run --with qdrant-client scripts/qdrant_setup.py
"""

import os

from qdrant_client import QdrantClient, models

VERSIONED = "rag_chunks_qwen3e06b_v1"  # model + contract version in the name
ALIAS = "rag_chunks"  # what applications use

client = QdrantClient(
    url=os.environ.get("QDRANT_URL", "http://127.0.0.1:6333"),
    api_key=os.environ["QDRANT_API_KEY"],
    prefer_grpc=False,
)

if not client.collection_exists(VERSIONED):
    client.create_collection(
        collection_name=VERSIONED,
        vectors_config={
            "dense": models.VectorParams(
                size=1024, distance=models.Distance.COSINE, datatype=models.Datatype.FLOAT16
            )
        },
        sparse_vectors_config={"sparse": models.SparseVectorParams()},  # for hybrid search, Step 32
        hnsw_config=models.HnswConfigDiff(m=16, ef_construct=100),
        quantization_config=models.ScalarQuantization(
            scalar=models.ScalarQuantizationConfig(type=models.ScalarType.INT8, always_ram=True)
        ),
    )
    indexes: dict[str, models.PayloadSchemaType | models.KeywordIndexParams] = {
        "tenant_id": models.KeywordIndexParams(
            type=models.KeywordIndexType.KEYWORD, is_tenant=True
        ),
        "acl_groups": models.PayloadSchemaType.KEYWORD,
        "classification": models.PayloadSchemaType.KEYWORD,
        "document_id": models.PayloadSchemaType.INTEGER,
    }
    for field, schema in indexes.items():
        client.create_payload_index(VERSIONED, field_name=field, field_schema=schema)
    print("created", VERSIONED)

client.update_collection_aliases(
    change_aliases_operations=[
        models.CreateAliasOperation(
            create_alias=models.CreateAlias(collection_name=VERSIONED, alias_name=ALIAS)
        )
    ]
)
print("alias", ALIAS, "->", VERSIONED)
print(client.get_collection(VERSIONED).config.params)
