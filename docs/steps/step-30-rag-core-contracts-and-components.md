# Step 30 · The RAG core: contracts and switchable components

*Step 30 of 38 · Phase H · RAG core*

## At a glance

| | |
|---|---|
| **Goal** | One reusable library, `rag-core`, that every RAG project builds on. Every part of a RAG pipeline (parser, chunker, embedder, vector store, keyword index, retriever, reranker, generator, guardrail…) is defined once as a contract, has several named implementations, and is picked per environment in a config file, `rag.yaml`. Swapping pgvector for Qdrant, or switching the reranker off, is a one-word change with no code changes. |
| **How, in one sentence** | Small Python Protocols describe each part; a registry names the implementations; a Container reads a profile from `rag.yaml` (with inheritance and environment-variable overrides), validates every parameter, builds each component once and wires their dependencies; a conformance kit proves any implementation, ours or a project's, behaves like the others. |
| **Time** | About 2 hours. |
| **You'll end up with** | `libs/rag-core`: the shared vocabulary (`types.py`), the contracts (`contracts.py`), the registry and Container, profiles (`config.py`), a `rag` command line · the first built-in components: token counters, the gateway LLM client, an offline LLM and embedder, in-memory vector and BM25 stores · a conformance kit that checks ranking, idempotency, deletes, filters and, above all, access control (no cross-group, cross-clearance or cross-tenant result) · a way for any project to add its own components without touching rag-core (entry points) · 21 new tests in the guide (284 in total in the guide's count); ADR-0030. |
| **New words** | contract, Protocol (structural typing), component, slot, registry, dependency injection, container, profile, configuration as code, override, plugin, entry point, conformance test, reference implementation. |

## Why this phase exists

Steps 1 to 29 built everything *around* a RAG application: model serving and the gateway, the stores,
sign-in and policy, observability, audit, prompts, evaluations, a secured supply chain, dynamic secrets and
GitOps. Steps 11 to 13 deliberately left the RAG work itself (turning documents into searchable chunks,
finding the right ones, and writing an answer from them) to "later projects".

A review of all 29 steps against what a production RAG system needs showed that this was the biggest gap:
every project would have had to build its own ingestion, retrieval, ranking, answer generation and
guardrails, each slightly differently. Phase H puts that core into the foundation, once, tested, with every
major technique available as a switchable option:

| Step | What it adds |
|---|---|
| 30 | The contracts, the registry and `rag.yaml`: how every part becomes switchable (this step) |
| 31 | Ingestion: parsing, cleaning, PII redaction, six chunking strategies, enrichment, embedding, indexing into pgvector, Qdrant or OpenSearch, a job queue |
| 32 | Retrieval and ranking: dense, keyword and hybrid search, rank fusion, query rewriting, multi-query, HyDE, reranking, diversity, parent expansion |
| 33 | Augmentation and generation: context packing, citations that are checked, abstaining, streaming, conversations, caching, `/v1/answer` |
| 34 | Guardrails: prompt injection, PII, topics, groundedness, toxicity, at input, context and output |
| 35 | RAG architectures as pipelines: naive, advanced, conversational, corrective, self-reflective, adaptive, agentic, GraphRAG, SQL |

Phase I then covers the data lifecycle and threat model (36), production environments and operations (37),
and the reuse kit that lets a new project start from all of this in minutes (38).

## The big idea

> **ANALOGY · THE WALL SOCKET**
> You can plug any lamp into any socket, in any room, without rewiring the house. That works because the
> socket is a standard: its shape, voltage and safety rules are agreed. Lamps compete on everything else.
> rag-core makes each part of a RAG pipeline a socket:
> - the **contract** is the socket's standard ("a vector store can upsert, delete, search with access rules,
>   and count");
> - each **implementation** is a lamp (pgvector, Qdrant, OpenSearch, in-memory);
> - **`rag.yaml`** is which lamp is plugged in, room by room (your laptop, CI, staging, production);
> - the **conformance tests** are the safety certificate every lamp must pass before it's sold.

### The slots of a RAG pipeline (Figure 96)

By the end of Phase H, rag-core provides these implementations for each slot. Every slot is a contract
(Protocol) plus named implementations; `rag.yaml` picks one per slot, per environment.

| Area | Slot | Implementations (by the end of Phase H) |
|---|---|---|
| Ingestion | parsers | md · html · pdf · docx · csv · tika · docling |
| | normalizers | unicode · boilerplate |
| | pii | regex · presidio |
| | chunker | fixed · recursive · structure · window · semantic · parent-child |
| | enrichers | context-header · llm-context · questions |
| | embedder | gateway · cached · hashing |
| Storage | vector_store | pgvector · qdrant · opensearch-knn · memory |
| | keyword_index | postgres-fts · opensearch · memory-bm25 |
| | manifest · queue | postgres · memory / valkey-streams · memory |
| Query & answer | query_transformer | rewrite · multi-query · HyDE · decompose (Step 32) |
| | retriever · fusion · reranker | dense · sparse · hybrid / RRF · weighted / cross-encoder · LLM |
| | context · generator · guards | Steps 33-34 |
| | pipeline | naive · advanced · corrective · agentic · graph (Step 35) |

This step ships the machinery plus the first, service-free built-ins (in **bold** they exist now):
**token_counter: approx, hf-tokenizer · llm: gateway, scripted · embedder: hashing · vector_store: memory ·
keyword_index: memory-bm25**.

## What we're doing

1. Agree the vocabulary: `Source`, `Document`, `Element`, `Chunk`, `Query`, `Principal`, `ScoredChunk`, `Answer`.
2. Write the contracts, one small Protocol per kind of component.
3. Build the registry (names → factories) and the Container (profile → built, wired components).
4. Add profiles to `rag.yaml`, with inheritance and environment overrides.
5. Ship the first components and the conformance kit.
6. Give it a command line (`rag components`, `rag config check|validate|show`), test it, and record ADR-0030.

## Why we're doing it this way

> **WHY THIS MATTERS**
> RAG quality depends on dozens of choices: chunk size, embedding model, keyword or vector or both,
> reranker or not, how many results, which prompt. The right answer differs per corpus, and it changes as
> models improve. Three things follow:
> - You must be able to change one part without touching the rest, or every experiment becomes a rewrite.
> - You must be able to compare options on equal terms, which Step 26's harness does only if the options
>   are interchangeable.
> - Every project must get the same safety guarantees (access control in every store, PII handling, audit)
>   without re-implementing them.

| Need | How this step meets it |
|---|---|
| Swap any part without code changes | Contracts + registry + `rag.yaml`; switching is a one-word config change |
| Different setups per environment | Profiles with `extends`; laptop/CI use `offline`, the platform uses `local` |
| Change one setting at deploy time | `RAG__<SLOT>__<PARAM>` environment overrides (Kubernetes, CI) |
| Catch configuration mistakes before they bite | Every parameter validated (types, ranges, unknown keys); "did you mean …?" |
| Test without services | `offline` components: deterministic embedder and LLM, in-memory stores |
| New implementations behave like the old ones | Conformance kit, including access-control checks |
| Projects add their own parts | `register()` in their code, discovered through an entry point |
| Know what's available and how proven it is | `rag components`: every implementation, its parameters and its test status |

> **IN A COMPANY**
> This is the shape of every serious internal platform: a *paved road* (a supported, secure default) with
> *escape hatches* (documented ways to plug in something else). Frameworks such as LangChain, LlamaIndex
> and Haystack offer similar abstractions with far more integrations. Teams still often keep a thin layer of
> their own on top, for the reasons in this step: their own access-control rules enforced in every store,
> their own observability and audit, their own tested defaults, and freedom to change frameworks. rag-core
> is that thin layer, and nothing stops a component from wrapping a framework's class (the Alternatives
> section shows how).

## Key ideas

| Term | Plain-English meaning |
|---|---|
| Contract / Protocol | A list of methods a component must have. Python's `Protocol` checks it by shape: no base class needed. |
| Component | One implementation of a contract, e.g. the Qdrant vector store. |
| Slot | A role in a pipeline (`vector_store`, `reranker`, …) that exactly one component (or a list, for plural slots) fills. |
| Registry | The phone book of components: kind + name → how to build it, its parameters, a summary and its test status. |
| Container / dependency injection | Builds the components a profile names and hands each the others it needs (the HyDE transformer gets the LLM). |
| Profile | A named set of choices in `rag.yaml` (`offline`, `local`, …). `extends` copies another profile and changes some parts. |
| Override | `RAG__RERANKER__TOP_N=5`: change one parameter for one deployment, without editing the file. |
| Entry point | A standard Python packaging hook: a project declares "my components live in this module", and rag-core loads them. |
| Conformance test | The same test suite run against every implementation of a contract. |
| Status: live / mocked / reference | How a component is tested here: against the real service, against its exact HTTP requests, or not at all (needs heavy extras); shown by `rag components`. |

Some of these in more everyday words:

- **Protocol (structural typing).** Think of a job description rather than a family tree. A class does not
  have to say "I am a VectorStore" (inherit from a base class); if it has `upsert`, `delete_document`,
  `search` and `count` with the right shapes, it *is* one. mypy checks that at type-check time, and because
  the Protocols are `@runtime_checkable`, a test can also ask `isinstance(store, VectorStore)`.
- **Dependency injection.** A component never goes looking for the things it needs (no global
  "the LLM"); it is *handed* them by the Container. That is what lets a test hand it a fake one.
- **Configuration as code.** The choices live in a reviewed, versioned file (`rag.yaml`), checked by CI like
  code, not in someone's head or a dashboard.
- **Reference implementation.** The simple, obviously-correct version (exact cosine search, textbook BM25)
  that faster, real implementations are compared against.
- **Plugin.** A component that lives in another package and is found at run time, so adding it needs no
  change to rag-core.

### How a profile becomes running components (Figure 97)

```
rag.yaml                                  Container                                      built components
profiles:                                                                                embedder     → GatewayEmbedder
  offline (tests, CI)                     1 merge profile + extends + env                vector_store → PgVectorStore
  local extends offline                   2 look up each slot's component                chunker      → StructureChunker
  local-engines extends local             3 validate its parameters                      reranker     → (switched off)
environment                               4 build it once; build what it needs
  RAG_PROFILE=local                         (llm, embedder) on demand
  RAG__RERANKER__USE=none
```

Mistakes are explained before anything runs: unknown names (with a "did you mean"), bad or extra
parameters, missing dependencies and packages, circular profiles. `rag config validate` needs no services.
(The component names on the right are the ones later steps add; in this step the offline built-ins fill the
slots.)

## How to do it

On your Mac, in the project:

```bash
cd ~/dev/rag-platform
git switch -c feat/rag-core
mkdir -p libs/rag-core/src/rag_core/{components,testing} libs/rag-core/tests
```

### 1 · The package

File: [`libs/rag-core/pyproject.toml`](../../libs/rag-core/pyproject.toml). It declares the package, its four
small dependencies (`rag-common`, `pydantic`, `pyyaml`, `httpx`), optional extras, and the `rag` command:

```toml
[project.optional-dependencies]
# Each extra pulls in what ONE family of components needs, so a project installs only what it uses
pdf = ["pypdf>=6.0"]
docx = ["python-docx>=1.2"]
postgres = ["psycopg[binary]>=3.2", "pgvector>=0.4"]
valkey = ["redis>=6.0"]

[project.scripts]
rag = "rag_core.cli:main"
```

> **READING THE PACKAGE**
> - **Optional extras:** a project that only uses Markdown and Qdrant doesn't install a PDF library or a
>   Postgres driver. `rag-core[pdf,postgres]` adds what's needed; a component whose extra is missing says
>   exactly which one to install.
> - The `rag` command comes with the package.
> - **Workspace member:** `libs/*` is already in the uv workspace (Step 2), so `uv sync --all-packages`
>   installs it. Add `rag_core` to ruff's `known-first-party`, `libs/rag-core/src` to mypy's `files`, and
>   `rag-core` to the licence check's own-packages list (Step 27). The Dockerfile copies its
>   `pyproject.toml` like every member's (Step 27's test reminds you if you forget).

All four of those wiring changes are in this commit: [`pyproject.toml`](../../pyproject.toml) (ruff, mypy,
plus the `libs/rag-core/tests` folder so the tests are type-checked too), [`ci/licence-policy.yaml`](../../ci/licence-policy.yaml)
and [`services/rag-api/Dockerfile`](../../services/rag-api/Dockerfile).

### 2 · The vocabulary

File: [`libs/rag-core/src/rag_core/types.py`](../../libs/rag-core/src/rag_core/types.py). Every component takes
and returns these frozen dataclasses, so any parser can feed any chunker, any retriever any reranker:

```
Source ──parse──▶ Document(elements) ──chunk──▶ Chunk ──embed──▶ stored
Query ──transform──▶ queries ──retrieve──▶ ScoredChunk ──rerank──▶ Context ──generate──▶ Answer
```

| Type | What it is |
|---|---|
| `Access` | Who may see something: `classification` (public / internal / confidential / restricted), `groups`, `tenant`. `allows(principal)` is the one rule. |
| `Principal` | Who is asking, as decided by the policy engine: subject, groups, classifications, tenant; plus a `fingerprint`. |
| `Source` | Raw bytes plus their URI, MIME type, access and metadata; `sha256` of the bytes. |
| `Element` | One structural piece of a parsed document: title, heading, paragraph, list, table, code, caption, page break. |
| `Document` | A parsed source: its elements, title, the SHA-256 of the original bytes, access, language. |
| `Chunk` | The unit that is embedded, indexed, retrieved and cited: stable `id`, `text`, `embed_text`, `token_count`, `access`, optional `parent_id`. |
| `Query` / `Turn` | A question with its principal, metadata filters, conversation history and `k`. |
| `ScoredChunk` | A chunk with its score and every stage's score (`with_score(score, stage)` adds one). |
| `Citation` / `Answer` | The answer text, its `[n]` citations, and whether it abstained or was blocked, plus usage and trace. |

The access rule, in full:

```python
def allows(self, principal: Principal) -> bool:
    if self.tenant != principal.tenant or self.classification not in principal.classifications:
        return False
    return self.classification == "public" or bool(set(self.groups) & set(principal.groups))
```

> **READING THE TYPES**
> - `Access` travels with the content, from the source to every chunk in every store. Its fields are
>   Step 11's columns and Step 18's policy inputs, so the same rule applies everywhere: right tenant,
>   cleared for the classification, and either public or sharing a group.
> - `Principal` is the result of Step 18's decision, not the raw token: the groups and classifications this
>   person may see. Its `fingerprint` identifies "everyone who sees exactly the same documents", which
>   caches use (Step 33).
> - `Chunk.text` vs `embed_text`: what is shown and cited never changes; what is embedded may add a title, a
>   section path or generated context (Step 31).
> - **Stable chunk ids** (a hash of document, position and text): ingesting the same thing twice produces
>   the same ids, so writes are idempotent everywhere.
> - `ScoredChunk.scores` keeps every stage's score (dense, sparse, fused, reranked): explanations,
>   debugging and evaluation need them.
> - `Answer` distinguishes three outcomes: an answer, an honest abstention ("the documents don't say"), and
>   a block by a guardrail.

### 3 · The contracts

File: [`libs/rag-core/src/rag_core/contracts.py`](../../libs/rag-core/src/rag_core/contracts.py). One small
Protocol per kind, in pipeline order:

| Area | Kinds |
|---|---|
| ingestion | parser · normalizer · pii · chunker · enricher · token_counter · embedder |
| storage | vector_store · keyword_index · cache · queue |
| query | query_transformer · retriever · fusion · reranker · postprocessor |
| answer | context_builder · generator · guard · memory |

For example, the vector store:

```python
@runtime_checkable
class VectorStore(Protocol):
    def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None: ...
    def delete_document(self, document_uri: str) -> int: ...
    def search(self, vector: Sequence[float], principal: Principal, k: int,
               filters: dict[str, object] | None = None) -> list[ScoredChunk]: ...
    def count(self) -> int: ...
```

The others: `Parser.parse(source) -> Document` (with the `mime_types` it handles),
`Normalizer.normalize(document)`, `PiiRedactor.redact(text) -> (text, kinds found)`, `TokenCounter.count`,
`Chunker.chunk`, `Enricher.enrich`, `Embedder` (`model`, `dimensions`, `embed_documents`, `embed_query`),
`KeywordIndex` (`index`, `delete_document`, `search` with the principal), `QueryTransformer.transform(query) ->
list[str]`, `Retriever.retrieve(query, texts)`, `Fusion.fuse(ranked lists)`, `Reranker.rerank(query,
candidates, k)`, `PostProcessor.process`, `ContextBuilder.build -> Context` (text, the chunks in the order
shown, tokens), `Generator` (`generate` and `stream`), `LLM.complete(system, user, …)`, and
`Guard.check(query, payload) -> Verdict` (allow / redact / block / flag, with reasons and a replacement).

> **WHY PROTOCOLS, NOT BASE CLASSES**
> A Protocol says what a component must *do*, not what it must inherit from. A project can wrap a
> LlamaIndex retriever, a vendor SDK or ten lines of its own code, and it fits as long as the methods match.
> mypy checks the shape; `runtime_checkable` lets tests check it too. And every contract carries the
> principal where it matters: there's no way to call a store's search without saying who is asking.

### 4 · The registry and the Container

File: [`libs/rag-core/src/rag_core/registry.py`](../../libs/rag-core/src/rag_core/registry.py).

An implementation registers itself with a decorator, naming its kind, its name, a Pydantic model of its
parameters, a one-line summary, how it is tested, and any extras it needs:

```python
@register("reranker", "cross-encoder", params=CrossEncoderParams, summary="…", status="live")
def _cross_encoder(p: CrossEncoderParams, c: Container) -> Reranker: ...
```

A config file then says `reranker: {use: cross-encoder, top_n: 8}`, and the Container builds it, with its
parameters validated and its own dependencies (an LLM, an embedder) built on demand.

The pieces:

- `register(kind, name, *, params, summary, status, requires)` stores a `Spec`; registering the same name
  twice is an error (a project can't silently replace a built-in).
- `kinds()`, `specs(kind)`, `spec(kind, name)` look things up. `spec` explains unknown names with
  `difflib`: *no embedder named 'hashng'; did you mean 'hashing'? (available: hashing)*.
- `SLOTS` maps each slot to the kind that may fill it: `llm` and `judge_llm` are both of kind `llm`;
  `parsers`, `normalizers`, `enrichers`, `postprocessors` and `guards` are **plural** (a list applied in
  order).
- `Container(config, profile)`:
  - `get(slot)` builds a slot once and caches it; an unknown slot, a circular dependency, or a slot the
    profile doesn't configure ("profile 'p' doesn't configure 'llm', but something needs it") are clear
    errors.
  - `_build` accepts `name` or `{use: name, …params}`, validates the parameters (`extra="forbid"`, so a typo
    is an error), and turns a missing optional package into "needs a package that isn't installed: X
    (install the extra: rag-core[X])" and any start-up failure into "slot 'name' could not start: …".
  - `validate()` checks names and parameters **without building anything**: no connections, no secrets.
  - `build_all()` builds every configured slot (what `rag config check` does); `has(slot)` says whether a
    slot is configured and not switched off.
- `describe()` lists every component with its parameters, defaults and status.
- `_load_builtins()` imports every module in `rag_core.components` once, then every package's
  `rag_core.components` entry point.

> **READING THE REGISTRY**
> - `@register(kind, name, params=…)`: each implementation declares a Pydantic model of its parameters with
>   `extra="forbid"`. A typo like `dimension:` instead of `dimensions:` is an error, not a silently ignored
>   setting.
> - **Slots and kinds:** a slot is a role; its kind says which components may fill it. `llm` and `judge_llm`
>   are two slots of kind `llm` (a fast model for rewriting, a strong one for judging). Plural slots
>   (`parsers`, `guards`, …) take a list applied in order.
> - **The Container builds lazily, once, with dependencies:** when the HyDE query transformer (Step 32) asks
>   for `c.get("llm")`, the LLM is built then. A missing dependency names the slot that needed it; a circular
>   one is refused.
> - `validate()` checks names and parameters without building anything: no connections, no secrets. CI
>   validates every profile, including production ones, this way.
> - **Startup errors name the slot:** a component that can't start (missing key, unreachable service) raises
>   `ComponentError` saying which slot and component, instead of a bare `KeyError` deep in a library.
> - **Plugins:** components in other packages are found through the `rag_core.components` entry point, so a
>   project adds its own parser or store without a fork.

A project's own components, in its `pyproject.toml`:

```toml
[project.entry-points."rag_core.components"]
my_parsers = "my_project.parsers"      # a module whose @register calls run when rag-core loads it
```

### 5 · Profiles in rag.yaml

File: [`libs/rag-core/src/rag_core/config.py`](../../libs/rag-core/src/rag_core/config.py). It turns a
`rag.yaml` document into one flat configuration for the Container:

```yaml
version: 1
profiles:
  base:
    chunker: {use: structure, max_tokens: 400}
    reranker: {use: cross-encoder, top_n: 8}
  dev:
    extends: base
    reranker: none          # switched off for this profile
```

- **Selecting** a profile: `RAG_PROFILE=dev` (or the `--profile` argument).
- `resolve(doc, profile, env)` follows the `extends` chain (refusing circles and unknown parents), merges
  from the root down, applies environment overrides, and drops every slot set to `none`.
- **Overrides:** `RAG__RERANKER__TOP_N=5`, `RAG__RERANKER__USE=none`. Double underscores mean nesting; the
  values are parsed as YAML, so numbers arrive as numbers.
- `load(path, profile, env)` reads the file and returns a ready `Container`.

File: [`rag.yaml`](../../rag.yaml) (first version; Steps 31-35 add to it):

```yaml
version: 1
profiles:
  # Runs anywhere, with nothing else running: tests, CI, demos, a new laptop
  offline:
    token_counter: approx
    llm: {use: scripted, default: "I don't know."}
    embedder: {use: hashing, dimensions: 256}
    vector_store: memory
    keyword_index: memory-bm25

  # The platform on your Mac (Compose / OrbStack): real models through the gateway
  local:
    extends: offline
    llm: {use: gateway, model: qwen-fast, base_url: "http://litellm:4000/v1"}
    judge_llm: {use: gateway, model: qwen-quality, base_url: "http://litellm:4000/v1"}
```

> **READING THE MERGE RULES**
> - **Same component, new parameters:** `embedder: {dimensions: 64}` under `extends` keeps `use: hashing`
>   and changes only the size.
> - **Another component:** `llm: {use: gateway}` replaces the whole entry; the old component's parameters
>   don't leak into the new one.
> - **Switching off:** `reranker: none` (or `RAG__RERANKER__USE=none`) removes the slot.
> - **Overrides are YAML-typed:** `RAG__EMBEDDER__DIMENSIONS=128` arrives as the number 128.

### 6 · The first components and the conformance kit

File: [`libs/rag-core/src/rag_core/components/basics.py`](../../libs/rag-core/src/rag_core/components/basics.py).
The in-memory and fake components aren't toys: they make every pipeline runnable and testable on a laptop
with nothing else running, and they are the reference the real adapters are compared to.

| Kind | Name | Status | What it does | Parameters |
|---|---|---|---|---|
| token_counter | `approx` | live | characters/4, at least one per word; no model files | `chars_per_token=4.0` |
| token_counter | `hf-tokenizer` | reference | exact counts with the embedding model's own `tokenizer.json` (extra: tokenizers) | `tokenizer_file` (required) |
| llm | `gateway` | mocked | any model behind the LiteLLM gateway (OpenAI-compatible chat completions); retries once on 429/5xx | `model='qwen-fast'`, `base_url='http://litellm:4000/v1'`, `api_key_env='LLM_GATEWAY_KEY'`, `timeout=120.0`, `max_retries=1` |
| llm | `scripted` | live | canned replies for tests and offline demos (matches substrings of the prompt) | `replies={}`, `default=''` |
| embedder | `hashing` | live | offline, deterministic word-hash vectors (hashed words and word pairs, L2-normalised) | `dimensions=256` (16-4096) |
| vector_store | `memory` | live | exact cosine search in memory, with the access rule and metadata filters | none |
| keyword_index | `memory-bm25` | live | Okapi BM25 keyword ranking in memory, with the access rule and metadata filters | `k1=1.5`, `b=0.75` |

Two helpers are shared by every store: `words(text)` (a Unicode word tokenizer that keeps "don't" whole)
and `matches_filters(chunk, filters)` (metadata equality; a list value means "any of").

> **READING THE BUILT-INS**
> - **`gateway` LLM:** every model call from every pipeline goes through LiteLLM (Step 9), so budgets,
>   fallbacks, rate limits and logs (Steps 10, 22) apply automatically. The key is read from an environment
>   variable whose *name* is configured; the value never appears in `rag.yaml`.
> - **`hashing` embedder and `scripted` LLM:** deterministic and offline. They make every pipeline testable
>   without a GPU. The hashing embedder captures word overlap, not meaning: never use it for real quality
>   judgements.
> - **`memory` vector store and `memory-bm25`:** exact search and textbook BM25. Small corpora and tests use
>   them directly; the real stores are measured against them.

File: [`libs/rag-core/src/rag_core/testing/conformance.py`](../../libs/rag-core/src/rag_core/testing/conformance.py).
The same checks for every implementation of a contract. A project that writes its own store runs them in its
tests:

```python
from rag_core.testing.conformance import check_vector_store
def test_my_store_conforms(): check_vector_store(lambda: MyStore(...), HashingEmbedder(64))
```

It uses five sample chunks (an HR leave policy in two chunks, a confidential salary note, a public handbook
line and an engineering note) and three people: Alice (HR, cleared to confidential), Bob (engineering,
cleared to internal) and Carol (like Alice, but in another tenant).

- `check_embedder`: vectors have `dimensions` entries, are finite, and the embedder names its model.
- `check_vector_store`: upsert, re-upsert the same id (no duplicate), best hit is the leave policy, results
  are best-first, the access checks, then delete returns the number removed and they are really gone.
- `check_keyword_index`: the same for keyword search ("parental leave weeks" finds the parental-leave chunk).
- `_check_access`: no confidential chunk for Bob, no HR-only chunk for Bob, no engineering chunk for Alice,
  nothing at all for another tenant, and metadata filters respected.

> **THE ACCESS CHECKS ARE THE POINT**
> `_check_access` fails with the word **LEAK** if any store returns a chunk to someone outside its group,
> below its clearance, or in another tenant. Every vector store and keyword index in Phase H passes it
> against the real service (pgvector, Postgres full-text search, Qdrant) or its exact requests
> (OpenSearch). A project that writes its own store runs the same function in its tests before anyone may
> use it.

### 7 · The command line

File: [`libs/rag-core/src/rag_core/cli.py`](../../libs/rag-core/src/rag_core/cli.py).

```
rag components [--kind reranker] [--json]                 what can be switched, and to what
rag config check    [--file rag.yaml] [--profile dev]     build every component of a profile
rag config validate [--file rag.yaml] [--profile prod]    names and parameters only: no services
rag config show     [--file rag.yaml] [--profile dev]     the resolved profile (after extends + env)
```

`--file` defaults to `$RAG_CONFIG` or `rag.yaml`; the profile defaults to `$RAG_PROFILE`. Every
`ComponentError` is printed as `ERROR: …` with exit code 1.

```text
$ uv run rag components
embedder           hashing                live      offline, deterministic word-hash vectors (tests, CI, demos)
                                                    dimensions=256
keyword_index      memory-bm25            live      BM25 keyword ranking in memory (dev, tests)
                                                    k1=1.5, b=0.75
llm                gateway                mocked    any model behind the LiteLLM gateway (OpenAI-compatible chat completions)
                                                    model='qwen-fast', base_url='http://litellm:4000/v1', api_key_env='LLM_GATEWAY_KEY', timeout=120.0, max_retries=1
llm                scripted               live      canned replies for tests and offline demos
                                                    replies={}, default=''
token_counter      approx                 live      characters/4, at least one per word; no model files
                                                    chars_per_token=4.0
token_counter      hf-tokenizer           reference exact counts with the embedding model's own tokenizer.json   [extra: tokenizers]
                                                    tokenizer_file=<required>
vector_store       memory                 live      exact cosine search in memory (dev, tests, small corpora)
```

```text
$ uv run rag config check --profile offline
ok   token_counter      ApproxTokenCounter
ok   llm                ScriptedLLM
ok   embedder           HashingEmbedder
ok   vector_store       MemoryVectorStore
ok   keyword_index      MemoryKeywordIndex
profile 'offline': 5 slot(s) built
```

```text
$ RAG__EMBEDDER__DIMENSIONS=64 RAG__KEYWORD_INDEX=none uv run rag config show --profile local
profile: local
token_counter: approx
llm:
  use: gateway
  model: qwen-fast
  base_url: http://litellm:4000/v1
embedder:
  use: hashing
  dimensions: 64
vector_store: memory
judge_llm:
  use: gateway
  model: qwen-quality
  base_url: http://litellm:4000/v1
```

Mistakes, explained:

```text
$ RAG__EMBEDDER__USE=hashng uv run rag config check --profile offline
ERROR: no embedder named 'hashng'; did you mean 'hashing'? (available: hashing)

$ RAG__EMBEDDER__DIMENSION=64 uv run rag config check --profile offline
ERROR: embedder 'hashing': dimension: Extra inputs are not permitted
```

### 8 · Test it

Files: [`libs/rag-core/tests/test_registry.py`](../../libs/rag-core/tests/test_registry.py) (15 tests) and
[`libs/rag-core/tests/test_basics.py`](../../libs/rag-core/tests/test_basics.py) (6 tests): the guide's 21.

```bash
uv run pytest -q libs/rag-core      # 21 passed in the guide (50 here, see the notes)
just audit-test                     # 284 passed in the guide's count
```

> **WHAT THE TESTS PROVE**
> - Profiles build; `extends` merges or replaces correctly; `none` switches a slot off; overrides are typed.
> - Each kind of mistake gets its own clear message: unknown name (with a suggestion), unknown or
>   out-of-range parameter, wrong shape, unknown slot, circular profiles, a missing dependency, a component
>   that can't start.
> - A project's own component registers and builds like a built-in one, and can't silently replace one
>   (registering a name twice is refused).
> - Every component has a summary and a test status; every profile in the repository's `rag.yaml`
>   validates, and `offline` builds.
> - The built-ins pass the conformance kit; the gateway client sends the key as a header, retries once on
>   429/5xx and then fails with a clear message.

This repository adds [`libs/rag-core/tests/test_core_contracts.py`](../../libs/rag-core/tests/test_core_contracts.py)
(29 more tests) for the parts later steps lean on: the access rule case by case, fingerprints, stable chunk
ids, per-stage scores, metadata filters, every built-in satisfying its Protocol at run time, file-loading
errors (bad version, unknown profile or parent, not a mapping, invalid YAML, missing file), overrides that
switch a slot on, `extends` not mutating the parent, plural slots, circular component dependencies, the
missing-extra message, entry-point plugins, and the CLI's `components --json`, `show`, `check` and
`validate`.

### 9 · Record the decision

File: [`docs/adr/0030-build-rag-on-a-shared-core-of-switchable-components.md`](../adr/0030-build-rag-on-a-shared-core-of-switchable-components.md):
libs/rag-core with shared types, one Protocol per kind, a registry with validated parameters, status and
extras, a lazily-building Container, profiles with `extends`, `none` and `RAG__SLOT__PARAM` overrides,
`validate()` without building, entry-point plugins and a conformance kit every store must pass. Rejected:
a framework as the core (wrap them as components instead), every project building its own (the problem),
abstract base classes (force inheritance), Hydra/dynaconf (more concepts than needed).

```bash
git add -A
git commit -m "feat(rag-core): contracts, registry, profiles, conformance kit"
```

## Benefits

- **Switch anything with one word,** per environment, without code changes.
- **Experiments are cheap:** chunkers, stores, rerankers and models compared on the same data with Step 26.
- **Safety is uniform:** every store passes the same access-control tests.
- **Runs anywhere:** the `offline` profile needs no services, so tests and CI are fast and deterministic.
- **Mistakes surface early,** with messages that say what to fix.
- **Open for extension:** a project's own components plug in through an entry point.

## Drawbacks and risks

- **One more layer** between you and the libraries; debugging occasionally means reading both.
- **Lowest common denominator:** a contract can't expose every special feature of every store.
  Implementations take extra parameters for that, and a project can always use a store directly when it
  must.
- **Config can hide behaviour:** the resolved profile (`rag config show`) and the trace (Step 33) are how
  you see what actually ran.
- **"Offline" components are not quality references.** Hashing embeddings say nothing about real retrieval
  quality.

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| rag-core (this step) | A thin layer of our own contracts and config over any library | You need uniform security, audit and evaluation across many projects |
| LlamaIndex | A large framework for indexing and querying documents | Rapid prototyping; many data connectors |
| LangChain / LangGraph | Composable chains and agent graphs | Agent-heavy apps; its ecosystem of integrations |
| Haystack | Pipelines of components with typed connections | Search-heavy apps; a production-minded framework |
| DSPy | Programs whose prompts are optimised automatically | Prompt pipelines tuned against a metric |
| Vendor platforms (Bedrock Knowledge Bases, Vertex AI RAG Engine, Azure AI Search) | Managed RAG services | All-in on one cloud; less control, less to run |

Wrapping a framework class as a component takes a few lines (an example, not code in this repository):

```python
@register("retriever", "llamaindex", params=MyParams, status="reference", summary="wraps a LlamaIndex retriever")
def _li(p: MyParams, c: Container) -> Retriever:
    from llama_index.core import VectorStoreIndex
    index = VectorStoreIndex.from_vector_store(...)          # your LlamaIndex setup
    li = index.as_retriever(similarity_top_k=p.k)

    class Wrapped:
        def retrieve(self, query, texts):                    # the rag-core contract
            nodes = li.retrieve(texts[0])
            return [to_scored_chunk(n) for n in nodes if allowed(n, query.principal)]
    return Wrapped()
```

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| A platform team serving several RAG projects | rag-core as the paved road, frameworks wrapped where they add value |
| One prototype this week | A framework directly; move to rag-core when it heads for production |
| Heavy agent workflows | LangGraph or similar for orchestration, rag-core components for retrieval and safety |
| All-in on one cloud | The cloud's managed RAG, with Phase H's tests and evaluations as the quality bar |

## Common mistakes

- **Putting secrets in `rag.yaml`.** It holds the *names* of environment variables; values come from
  OpenBao or SOPS.
- **Silently ignoring unknown settings** (no `extra="forbid"`): the typo'd setting never takes effect and
  nobody notices.
- **A store that "trusts" the caller to filter results.** Access control belongs inside the store's query.
- **Building components at import time** (connecting to databases when a module loads): slow tests,
  surprising failures. Build lazily.
- **Testing new implementations only with happy paths.** The conformance kit exists so a new store is tested
  for leaks too.

## Done when

- [ ] `uv run rag components` lists the built-in components with their status
- [ ] `uv run rag config check --profile offline` builds every slot; `rag config validate --profile local` reports 0 problems
- [ ] `RAG__EMBEDDER__USE=hashng uv run rag config check --profile offline` suggests `hashing`
- [ ] `uv run pytest -q libs/rag-core` passes; `just audit-test` shows 284 passed (in the guide's count)
- [ ] ADR-0030 is committed

## Recap

> **RECAP**
> The RAG work now has a shape every project shares:
> - contracts for every part, checked by shape, carrying the principal wherever access matters
> - a registry and a Container that build what a profile names, validated, wired and lazily
> - profiles in `rag.yaml` with inheritance and environment overrides; `offline` runs anywhere
> - a conformance kit whose access checks every store must pass
>
> Next, Step 31: the first real use, an ingestion pipeline that turns PDFs, Word files, web pages, Markdown
> and spreadsheets into clean, redacted, well-cut, searchable chunks in any of three stores.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `libs/rag-core/pyproject.toml` | The `rag-core` package: dependencies, optional extras per component family, the `rag` command |
| `libs/rag-core/src/rag_core/__init__.py` | Package docstring: a map of the modules |
| `libs/rag-core/src/rag_core/py.typed` | Tells type checkers the package ships type hints |
| `libs/rag-core/src/rag_core/types.py` | The shared vocabulary: Access, Principal, Source, Element, Document, Chunk, Query, Turn, ScoredChunk, Citation, Answer |
| `libs/rag-core/src/rag_core/contracts.py` | One runtime-checkable Protocol per kind of component |
| `libs/rag-core/src/rag_core/registry.py` | `register`, `spec`, `describe`, the slots, and the Container that builds and validates profiles |
| `libs/rag-core/src/rag_core/config.py` | `rag.yaml` profiles: `extends`, `none`, `RAG__SLOT__PARAM` overrides, `load()` |
| `libs/rag-core/src/rag_core/components/__init__.py` | The package of built-in components, loaded once by the registry |
| `libs/rag-core/src/rag_core/components/basics.py` | Token counters, gateway and scripted LLMs, hashing embedder, memory vector store, memory BM25 |
| `libs/rag-core/src/rag_core/testing/__init__.py` | The reusable test helpers package |
| `libs/rag-core/src/rag_core/testing/conformance.py` | The conformance kit: embedder, vector store and keyword index checks, with LEAK checks |
| `libs/rag-core/src/rag_core/cli.py` | The `rag` command: `components`, `config check / validate / show` |
| `libs/rag-core/tests/test_registry.py` | The guide's 15 tests of profiles, overrides, mistakes, plugins and the repository's `rag.yaml` |
| `libs/rag-core/tests/test_basics.py` | The guide's 6 tests: built-ins pass the conformance kit; the gateway client's header and retries |
| `libs/rag-core/tests/test_core_contracts.py` | 29 extra tests: types, contracts, file loading, plural slots, plugins, the CLI |
| `rag.yaml` | The first profiles: `offline` (no services) and `local` (models through the gateway) |
| `pyproject.toml` (changed) | `rag_core` first-party for ruff; rag-core source and tests in mypy; lint exceptions for the CLI and kit; `tokenizers` import override |
| `uv.lock` (changed) | Locks rag-core and its optional extras |
| `ci/licence-policy.yaml` (changed) | `rag-core` is one of our own packages |
| `services/rag-api/Dockerfile` (changed) | Copies rag-core's `pyproject.toml`, as every workspace member's must be |
| `docs/adr/0030-build-rag-on-a-shared-core-of-switchable-components.md` | ADR-0030 |

## Notes for this repository

- **Ingestion commands come with Step 31.** The guide's `cli.py` already contains the `ingest`, `delete`,
  `enqueue` and `worker` subcommands, which import `rag_core.ingest` and `rag_core.components.queues`
  (written in Step 31). They are left out here so that the command, ruff and strict mypy work today; Step 31
  adds them to the same `rag` entry point.
- **Two of the guide's tests name Step 31 components.** `test_validate_finds_problems_without_connecting`
  uses `pgvector` and `test_startup_errors_name_the_slot` uses `pii: regex`, neither of which exists yet.
  Here the first uses the built-in `memory` store (which takes no parameters, so `dimensons` is equally an
  "Extra inputs are not permitted" error) and the second registers a test-only `pii` component that fails at
  start-up with the same `ValueError: pseudonymise needs a key`. Both assert exactly the behaviour the guide
  asserts; Step 31 can switch them back to the real components.
- **A `tokenizers` extra.** The `hf-tokenizer` token counter declares `requires=("tokenizers",)`, so its
  error message tells you to install `rag-core[tokenizers]`; the guide's `pyproject.toml` has no such
  extra, so one was added to make that message true. mypy ignores the missing `tokenizers` import (it is
  only installed with the extra).
- **Small robustness additions,** none changing the guide's behaviour: a plural slot given a single entry
  instead of a list is a clear `ComponentError` (the guide's code would iterate over the characters of the
  name); `config.load` turns a missing file, invalid YAML or a non-mapping document into a
  `ComponentError` (so `rag config …` prints `ERROR:` instead of a traceback); `describe()` shows a
  `default_factory` default as its value (`replies={}`) rather than `PydanticUndefined`; the pydantic
  validation messages are formatted by one shared helper.
- **Extra tests.** `test_core_contracts.py` adds 29 tests, so `uv run pytest -q libs/rag-core` reports 50
  here, not 21. The whole suite here reports 505 passed and 116 skipped (the skipped ones need Docker
  services or `just audit-test`); the guide's "284" is its own running count.
- **Validation here:** ruff, ruff format, strict mypy, the full pytest suite and every pre-commit hook pass in
  this Linux container; the CLI outputs above were produced here. The `local` profile was validated, not
  built against a running gateway (that needs the Step 9 stack on your Mac).
