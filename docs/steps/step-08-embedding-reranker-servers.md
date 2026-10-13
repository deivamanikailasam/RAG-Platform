# Step 8 · Embedding and reranker servers

*Step 8 of 38 · Phase B · Model serving*

## At a glance

| | |
|---|---|
| **Goal** | Run the two "search brain" models every RAG system needs, each as its own authenticated local server on the Metal GPU, then measure them: **Qwen3-Embedding-0.6B on `127.0.0.1:8083`** turns text into vectors; **bge-reranker-v2-m3 on `127.0.0.1:8084`** re-scores search results for relevance. |
| **Time** | About 75 minutes. |
| **You'll end up with** | Hugging Face Text Embeddings Inference (TEI) installed natively; both models pinned in the inventory, with a written embedding contract; an API key loaded from your encrypted secrets; a demo showing query instructions, Matryoshka truncation and reranking; benchmarks, launchd services and ADR-0008. |
| **New words** | Embedding, vector, dimension, meaning space, cosine similarity, normalisation, bi-encoder, cross-encoder, retrieve-then-rerank, query instruction, asymmetric retrieval, Matryoshka embeddings, pooling, truncation, batch, throughput, embedding contract, re-indexing. |

## The big idea

> **ANALOGY · A LIBRARIAN AND A SPECIALIST READER**
> Imagine a library with 100,000 pages.
>
> - **The embedding model is a librarian** who gives every page a set of map coordinates based on what it *means*.
>   Pages about remote working end up close together; pages about car parking end up far away. When a question
>   arrives, the librarian gives it coordinates too and grabs the 50 nearest pages. That's very fast, because the
>   pages were mapped in advance.
> - **The reranker is a specialist** who then reads the question and each of those 50 pages side by side, carefully,
>   and picks the best 5. Much slower per page, so it only ever sees a shortlist.
>
> Fast-and-broad, then slow-and-precise: that two-stage pattern is the heart of nearly every production RAG system.

## What we're doing

1. Install TEI (a Rust server with Metal support) from Homebrew.
2. Download both models, pin their revisions, and write down the **embedding contract**.
3. Add an API key to your encrypted secrets, and start each server so the key is never visible on the command line.
4. Call both servers: embed text, compare with and without the query instruction, try Matryoshka truncation, and
   rerank.
5. Benchmark embedding throughput and reranking latency.
6. Run both as launchd services, add `just` recipes, and write ADR-0008.

## Why we're doing this

> **WHY THIS MATTERS**
> In RAG, **retrieval quality caps answer quality**. If the right passage isn't retrieved, even the best LLM can only
> guess, or worse, make something up. The embedder decides what *can* be found. The reranker decides what the LLM
> actually *reads*. And because every document is embedded once and stored, the embedding model choice is the most
> expensive decision to change later.

| Need | How this step meets it |
|---|---|
| Turn text into vectors for semantic search (Projects 1–2) | Embedding server, OpenAI-compatible and TEI-native APIs |
| Precise ordering of the final few passages | Cross-encoder reranker server |
| Fast bulk indexing of thousands of chunks | TEI's dynamic batching on the Metal GPU |
| Vectors must stay comparable for the life of an index | A pinned embedding contract recorded in the inventory |
| No anonymous access, no secrets on display | `--api-key` from SOPS-encrypted secrets, via an environment variable rather than a command-line argument |
| Measured capacity | Chunks/second and rerank latency, recorded |

> **IN A COMPANY**
> Embedding and reranking are usually separate, shared services, because indexing jobs, search APIs and evaluation
> all call them, at very different volumes. Teams track which embedding model built which index, because a silent
> model change invalidates the whole index. That's a classic production incident: "search got worse overnight" turns
> out to be a dependency upgrade that changed the vectors.

## Key ideas

### Embeddings: meaning as coordinates

An embedding model reads a piece of text such as *"Can I work from home on Fridays?"* and outputs a long list of
numbers, for example `[0.021, -0.113, 0.087, … 1,024 numbers]`. That list is a point in **meaning space**. Texts with
similar meaning land close together; texts about different things land far apart. **Cosine similarity** measures how
close two points are.

*(Guide Figure 25: the question lands next to "remote working policy" (0.82) and "hybrid work rules" (0.74), and far
from "office car parking" (0.21) and "expense claims for taxis".)*

| Term | Plain-English meaning |
|---|---|
| Embedding / vector | A fixed-length list of numbers representing a text's meaning. |
| Dimensions | How many numbers are in the list (Qwen3-Embedding-0.6B: up to 1,024). More can capture more nuance, but costs more storage and search time. |
| Cosine similarity | A score for how closely two vectors point in the same direction: near 1 = very similar, near 0 = unrelated. |
| Normalisation | Scaling every vector to length 1, so cosine similarity becomes a simple dot product (TEI's `/embed` does this by default). |
| Pooling | How the model squeezes per-token outputs into one vector. Qwen3-Embedding uses the **last token**; TEI reads this from the model's config. |
| Max sequence length / truncation | The longest text the model reads. Anything beyond it is cut off. TEI's `--auto-truncate` (on by default) does this silently. |
| Batch / throughput | Embedding many texts in one GPU pass / how many texts per second the server handles. |

### Queries and documents are treated differently

Qwen3-Embedding is **instruction-aware**. Per its model card:

- **Queries** should be prefixed with a one-sentence task description, in the format
  `Instruct: {task}\nQuery:{query}`.
- **Documents** are embedded as they are, with no instruction.

This is called **asymmetric retrieval**: a short question and a long passage are different kinds of text, and the
instruction tells the model which "side" it's encoding. Forgetting the prefix is one of the most common ways teams
quietly lose retrieval quality.

> **IN PLAIN ENGLISH · MATRYOSHKA EMBEDDINGS**
> Like Russian nesting dolls, a Matryoshka embedding is trained so that its *first part* is already a useful smaller
> embedding. Qwen3-Embedding supports output sizes from 32 to 1,024 dimensions. Keep the first 256 numbers (then
> **re-normalise**) and you get a vector a quarter of the size, at a small quality cost. That's a huge saving when you
> store millions of vectors. You'll measure the trade-off in Step 32.

### Retrieve, then rerank

There are two kinds of model at work, and they are built differently:

- A **bi-encoder** (the embedder) turns the query into a vector and each document into a vector, *separately*. The
  document vectors are computed **once, in advance**, and compared with the query by cosine similarity in
  milliseconds. Great recall (it rarely misses the right passage entirely), but a rougher ranking.
- A **cross-encoder** (the reranker) reads the query and one document **together**, as a pair, and outputs a
  relevance score. Nothing can be precomputed, and each pair costs roughly 10–100 ms, so it is only used on a
  shortlist. In exchange it gives sharp precision on the top results.

Put together, the pipeline is: your whole collection (say 100,000 chunks) → **embedder + vector search** (fast, broad)
→ top 50 candidates → **reranker** reads each pair (slow, precise) → top 5 best → the LLM writes the answer with
citations to those 5.

*(Guide Figure 26: the two-stage pattern. A bi-encoder embedder narrows 100,000 chunks to about 50 in milliseconds; a
cross-encoder reranker reads each candidate with the question to pick the best 5 for the LLM.)*

### The embedding contract

Vectors only make sense when compared with vectors made **the same way**. The **embedding contract** is the list of
everything that defines "the same way":

- model repo + revision
- dimensions (e.g. 1024, or truncated)
- query instruction text
- normalisation (unit length)
- pooling (last-token for Qwen3)
- max tokens per chunk

Change **any** of these and every stored vector becomes incompatible: an index built with v1 and queries embedded with
v2 live in different coordinate systems, so the distances between them become meaningless, with no error message.
So the contract is pinned, recorded with every index, and changed only by a planned **re-index** (Capstone).

*(Guide Figure 27: vectors from different models, revisions, sizes or instructions live in different coordinate
systems. Change any part of the contract and the whole index must be re-embedded.)*

> **WHY WRITE IT DOWN?**
> The contract, meaning model + revision + dimensions + query instruction + normalisation + pooling + chunk length
> limit, will be stored with every index you build (Steps 11–12). When someone proposes "let's try the 4B model", the
> contract makes the true cost obvious: a full re-index, planned like a migration (Capstone: "safe embedding-model
> migration").

## How to do it

All commands run on the Mac, from the repository root (the guide's `~/dev/rag-platform`):

```bash
cd ~/dev/rag-platform
git switch -c feat/embeddings-reranker
```

### 1 · Install TEI

`bootstrap/Brewfile` gains a new section:

```ruby
# ---- Embeddings & reranking (Step 8) ----
brew "text-embeddings-inference"  # Hugging Face TEI: fast embedding/reranking server, native Metal build on Apple Silicon
```

```bash
just bootstrap
text-embeddings-router --version
text-embeddings-router --help | less     # read the options for YOUR version (press q to quit)
```

> **WHY TEI, AND WHY NATIVELY?**
> TEI is Hugging Face's production embedding server, written in Rust. It batches requests together automatically,
> exposes Prometheus metrics, supports API keys and OpenTelemetry tracing, and has both a native `/embed` / `/rerank`
> API and an OpenAI-compatible `/v1/embeddings`. Hugging Face documents the Homebrew build for Apple Silicon with
> Metal. Its Docker image on ARM is CPU-only, so, exactly like the LLMs (ADR-0004), it runs natively.

### 2 · Download, pin and record the models

```bash
uv run --project infra/model-serving hf download Qwen/Qwen3-Embedding-0.6B
uv run --project infra/model-serving hf download BAAI/bge-reranker-v2-m3
ls ~/.cache/huggingface/hub/models--Qwen--Qwen3-Embedding-0.6B/snapshots/
ls ~/.cache/huggingface/hub/models--BAAI--bge-reranker-v2-m3/snapshots/
```

(`just search-models-download` runs the two downloads for you.) The folder name inside `snapshots/` is the 40-character
revision SHA.

The servers load each model from its **exact local snapshot folder**. That pins the revision and needs no network
access at all. A small helper, `scripts/model-path.sh`, finds the folder:

```bash
scripts/model-path.sh Qwen/Qwen3-Embedding-0.6B            # newest snapshot folder
scripts/model-path.sh BAAI/bge-reranker-v2-m3 <sha>         # one exact revision
```

It honours `HF_HOME` if you moved the Hugging Face cache, and prints `not downloaded: <repo>` (exit 1) if the model
isn't there.

Both models are then added to the model inventory, `infra/model-serving/models.yaml`, including the embedding
contract:

```yaml
  - id: embedder
    repo: Qwen/Qwen3-Embedding-0.6B
    revision: <40-char SHA>
    format: safetensors (TEI, Metal)
    licence: Apache-2.0 (per the model card)
    port: 8083
    role: dense embeddings for indexing and queries
    contract:                       # changing ANY of these requires a full re-index
      dimensions: 1024              # model supports 32-1024 (Matryoshka); truncate client-side, then re-normalise
      normalise: true
      pooling: last-token           # read by TEI from the model config
      query_instruction: "Instruct: Given an employee question, retrieve passages from company documents that answer it\nQuery:"
      document_instruction: none
      max_chunk_tokens: 1024        # our chunkers (Step 31) must stay under this; TEI truncates silently beyond the model limit
    approved_by: <you>
    approved_on: 2026-10-12
  - id: reranker
    repo: BAAI/bge-reranker-v2-m3
    revision: <40-char SHA>
    format: safetensors (TEI, Metal), cross-encoder
    licence: <confirm on the model card>
    port: 8084
    role: rerank top-k retrieval candidates
    approved_by: <you>
    approved_on: 2026-10-12
```

Replace the `<40-char SHA>` placeholders with the folder names from the `ls` above, confirm the reranker's licence on
its model card, and put your name in `approved_by`.

### 3 · Add an API key and a safe launcher

Add a key for the embedding services to your encrypted secrets:

```bash
openssl rand -hex 24                      # copy the output
just secrets-edit                         # add a line:   TEI_API_KEY=<paste>   then save and close
just secrets-keys | grep TEI_API_KEY      # confirms it's there (name only)
```

The launcher `scripts/run-tei.sh` decrypts the key in memory and hands it to TEI through its `API_KEY` environment
variable (TEI reads every option from an environment variable of the same name, so `API_KEY` is the same as
`--api-key`):

```bash
#!/usr/bin/env bash
# Start one TEI server, with its API key from the encrypted secrets.
# The key travels as an environment variable, never as a command-line argument (visible to `ps`).
# Usage: run-tei.sh <model-dir> <port> <metrics-port> <served-name>
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"
export SOPS_AGE_KEY_FILE="${SOPS_AGE_KEY_FILE:-$HOME/.config/sops/age/keys.txt}"
exec sops exec-env secrets/dev.enc.env "API_KEY=\"\$TEI_API_KEY\" exec text-embeddings-router \
  --model-id '$1' --hostname 127.0.0.1 --port '$2' --prometheus-port '$3' \
  --served-model-name '$4' --json-output"
```

How it works: `sops exec-env` decrypts `secrets/dev.enc.env` into the environment of a child shell only; that shell
copies `TEI_API_KEY` into `API_KEY` and then *replaces itself* (`exec`) with the TEI server. The decrypted file never
touches the disk, and the key never appears in the process's argument list.

> **TWO DEFAULTS TO OVERRIDE**
>
> - TEI's `--hostname` defaults to `0.0.0.0` (every network interface). The launcher sets `127.0.0.1`.
> - Both servers would try to use metrics port `9000`, so each gets its own (`9083`, `9084`).
>
> After starting, check with `lsof` which addresses the metrics ports listen on. If they're on all interfaces, make
> sure the macOS firewall is on (System Settings → Network → Firewall).

> **WHY NOT `--api-key <value>`?**
> Every program's command-line arguments are visible to any user on the machine via `ps aux`, and often end up in
> logs and crash reports. Environment variables passed straight to one process are much less exposed. It's the same
> reasoning as Step 6's file-based container secrets.

The `justfile` gets two variables near the top and two foreground recipes:

```make
embed_model   := "Qwen/Qwen3-Embedding-0.6B"
rerank_model  := "BAAI/bge-reranker-v2-m3"

# Run the embedding / reranker servers in the foreground
serve-embed:
    scripts/run-tei.sh "$(scripts/model-path.sh {{embed_model}})" 8083 9083 qwen3-embedding-0.6b

serve-rerank:
    scripts/run-tei.sh "$(scripts/model-path.sh {{rerank_model}})" 8084 9084 bge-reranker-v2-m3
```

```bash
chmod +x scripts/model-path.sh scripts/run-tei.sh      # already executable in this repository
just serve-embed       # Terminal 1: watch the log until it reports it's ready
just serve-rerank      # Terminal 2
```

### 4 · Call the servers

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8083/health               # 200
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8083/embed \
     -H 'Content-Type: application/json' -d '{"inputs":"hi"}'                        # 401: no key, rejected
just with-secrets 'curl -s http://127.0.0.1:8083/embed -H "Authorization: Bearer $TEI_API_KEY" \
     -H "Content-Type: application/json" -d "{\"inputs\":\"hello\"}" | jq ".[0] | length"'   # 1024
```

`/health` is open (so monitoring can check it), but `/embed` without the key is refused with **401**. With the key,
one input comes back as one vector of **1,024** numbers.

Now the real lesson: `scripts/embed_demo.py` is a tiny demo showing instruction vs no instruction, Matryoshka
truncation, and the reranker. It embeds five short company-policy passages (documents: no instruction), then the
question *"Can I work from home on Fridays?"* twice, with and without the instruction, and prints three rankings by
cosine similarity: with instruction (1,024 dims), without instruction, and with only the first 256 dimensions
(re-normalised). Finally it asks the reranker to score the same five passages against the question.

```bash
just with-secrets uv run scripts/embed_demo.py      # or: just embed-demo
```

> **WHAT TO LOOK FOR**
>
> - All three embedding rankings should put the remote-work passages near the top, but the scores and gaps differ.
>   With the instruction, the right passage usually stands out more clearly.
> - The 256-dimension ranking is close to the full one: a quarter of the storage for a small change.
> - The reranker spreads the scores much further apart, and puts the most directly answering passage clearly first.
>   That sharpness is exactly why it's worth its cost on a shortlist.
>
> The "Friday learning sessions" passage is a deliberate **distractor**: it shares words ("Friday", "in-office") but
> doesn't answer the question. Watch how each method handles it.

### 5 · Benchmark

`scripts/bench_embeddings.py` warms both servers up, then:

- embeds **512 chunks of ~200 tokens** (a security-policy paragraph repeated) in **batches of 32**, and prints
  chunks per second;
- reranks **10** and then **50** candidates for the question "How do I report phishing?", and prints each latency in
  milliseconds.

```bash
just with-secrets uv run scripts/bench_embeddings.py      # or: just bench-embed
```

Add the results to `docs/benchmarks/models.md` (the table is already appended; fill in the blanks):

```markdown
## Embeddings and reranking (TEI <version>, date <YYYY-MM-DD>)

| Model | Test | Result | Notes |
|---|---|---|---|
| Qwen3-Embedding-0.6B | 512 × ~200-token chunks, batch 32 | ___ chunks/s | indexing 100k chunks ≈ ___ min |
| bge-reranker-v2-m3 | 10 candidates | ___ ms | |
| bge-reranker-v2-m3 | 50 candidates | ___ ms | latency budget for reranking per query |
```

To fill in "indexing 100k chunks": 100,000 ÷ (chunks/s) ÷ 60 = minutes.

> **TURN THE NUMBERS INTO DECISIONS**
>
> - **chunks/s** tells you how long a full re-index takes, the real cost of changing the embedding contract.
> - **50-candidate rerank latency** goes straight into the answer latency budget. If it's too slow, rerank fewer
>   candidates, or try a smaller reranker in Step 32.

### 6 · Always on, then record the decision

`scripts/install-tei-agents.sh` writes and loads two launchd agents, exactly like Step 7's model agents:

| Agent | Runs | API port | Metrics port | Served name | Log |
|---|---|---|---|---|---|
| `com.rag-platform.embedder` | `scripts/run-tei.sh <embedder snapshot>` | 8083 | 9083 | `qwen3-embedding-0.6b` | `~/Library/Logs/rag-platform/embedder.log` |
| `com.rag-platform.reranker` | `scripts/run-tei.sh <reranker snapshot>` | 8084 | 9084 | `bge-reranker-v2-m3` | `~/Library/Logs/rag-platform/reranker.log` |

Each agent starts at login (`RunAtLoad`), restarts after a crash (`KeepAlive`, throttled to once every 30 s), and gets
a minimal `PATH` (`/opt/homebrew/bin:/usr/bin:/bin`, so it finds `sops` and `text-embeddings-router`) plus
`SOPS_AGE_KEY_FILE`. Because the agent runs `run-tei.sh`, the key is still decrypted at start-up and passed by
environment. The script unloads any old version (`launchctl bootout`) before loading the new one (`launchctl
bootstrap`). Reference copies of the generated plists are in `bootstrap/home/Library/LaunchAgents/`.

New `justfile` recipes:

```make
# Always-on embedding + reranker services
search-models-up:
    EMBED_DIR="$(scripts/model-path.sh {{embed_model}})" RERANK_DIR="$(scripts/model-path.sh {{rerank_model}})" scripts/install-tei-agents.sh

search-models-down:
    -launchctl bootout gui/$(id -u)/com.rag-platform.embedder
    -launchctl bootout gui/$(id -u)/com.rag-platform.reranker

# Health of every model server (LLMs + embedder + reranker)
health: models-health
    @curl -sf -o /dev/null http://127.0.0.1:8083/health && echo "  embedder:8083 ok" || echo "  embedder:8083 DOWN"
    @curl -sf -o /dev/null http://127.0.0.1:8084/health && echo "  reranker:8084 ok" || echo "  reranker:8084 DOWN"
```

```bash
chmod +x scripts/install-tei-agents.sh                   # already executable in this repository
just search-models-up && sleep 20 && just health
lsof -nP -iTCP -sTCP:LISTEN | grep -E '808[1-4]|908[34]'   # check every listening address
```

`just health` first runs Step 7's `models-health` (8081, 8082) and then checks 8083 and 8084, so you see all four
model servers at once.

> **THE LAUNCHD AGENT NEEDS TO READ YOUR AGE KEY**
> Because `run-tei.sh` decrypts secrets at start-up, the agent needs `SOPS_AGE_KEY_FILE` (set in the plist). If the
> logs show a SOPS decryption error, check that path and the file's permissions (`chmod 600`).

Then record the decision:

```bash
just adr "Serve embeddings and reranking with TEI natively, behind an API key"
```

[ADR-0008](../adr/0008-serve-embeddings-and-reranking-with-tei-natively-behind-an-api-key.md) records the decision:
run TEI natively (Homebrew build, Metal), the embedder on 127.0.0.1:8083 and the reranker on 127.0.0.1:8084, loaded
from pinned snapshot folders, protected by `TEI_API_KEY` passed via environment, kept alive by launchd, with the
embedding contract recorded in `models.yaml` and stored with every index. It weighs llama.cpp's `llama-server`
(strong option, used to compare Qwen3-Reranker in Step 32), Ollama embeddings (no rerank endpoint), a custom FastAPI +
sentence-transformers service (we'd rebuild batching, auth and metrics), the Infinity server (smaller community) and
bigger embedders now (slower indexing; measure first). It is revisited when Step 32 evaluations show a better embedder
or reranker is worth the re-index or latency cost.

Add ADR-0008 to the index, fill in the SHAs and benchmark numbers, then:

```bash
git add -A
git commit -m "feat(models): TEI embedding and reranker servers with API key and embedding contract"
git push -u origin feat/embeddings-reranker
gh pr create --fill && gh pr merge --squash --delete-branch
git switch main && git pull
```

## Benefits

- **Both halves of retrieval are ready:** fast semantic recall (embedder) and sharp precision (reranker).
- **Production-grade serving:** dynamic batching, API-key auth, Prometheus metrics and OpenTelemetry support, all
  built in.
- **GPU speed natively,** consistent with the rest of the model layer.
- **Reproducible vectors:** pinned snapshots plus a written contract mean an index built today stays valid.
- **Secrets stay secret:** the key comes from SOPS and travels by environment variable, not command line.
- **Real numbers** for indexing time and rerank latency, ready for capacity and latency budgets.

## Drawbacks and risks

- **Silent truncation.** TEI cuts over-long inputs by default, so a chunk that's too long loses its end without an
  error. Chunkers must respect `max_chunk_tokens`, and Step 31 tests that.
- **Re-indexing cost.** Any contract change means re-embedding everything. Choose deliberately, migrate carefully.
- **More memory and processes.** Two more servers (a few GB together) on top of the LLMs.
- **Small baseline models.** 0.6B is fast but not the most accurate. Bigger embedders and other rerankers are
  evaluated, with numbers, in Projects 1–2.
- **Fixed model support.** TEI supports specific architectures. Qwen3-Reranker (an LLM-style reranker), for example,
  needs llama.cpp or a custom server.
- **The metrics port may listen beyond localhost** in some versions. Verify with `lsof`, and keep the firewall on.

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| **TEI (our choice)** | Hugging Face's Rust embedding/reranking server, Metal on Mac, CUDA on GPUs | Standard models, production features, same server locally and in the cloud |
| llama.cpp `llama-server` | `--embedding` for vectors, `--reranking` for `/v1/rerank`, GGUF models, Metal | GGUF models; LLM-based rerankers like Qwen3-Reranker; one engine for everything |
| Ollama | Simple model runner with an embeddings API | Quick prototypes needing only embeddings |
| Infinity | Python server for embeddings, reranking and multimodal | Many model types behind one server |
| Custom FastAPI + sentence-transformers / mlx-embeddings | Your own service code | Unusual models, custom pre/post-processing, research |
| Hosted APIs (OpenAI, Cohere, Voyage, Jina, Bedrock, Vertex) | Embeddings/rerank as a paid cloud service | Data may leave the machine, and you want zero ops or top-ranked models |

Model alternatives (compared properly in Projects 1–2):

| Role | Options |
|---|---|
| Embedders | Qwen3-Embedding 0.6B/4B/8B · bge-m3 (dense + sparse + multi-vector, multilingual) · nomic-embed · multilingual-e5 · EmbeddingGemma · Snowflake Arctic Embed |
| Rerankers | bge-reranker-v2-m3 · Qwen3-Reranker (via llama.cpp) · gte-reranker-modernbert · mxbai-rerank · LLM listwise reranking with your Qwen models (Step 32) |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Local RAG lab on Apple Silicon | TEI natively (this step), with llama.cpp for models TEI doesn't support |
| Production on NVIDIA GPUs | TEI CUDA images or vLLM (pooling models) behind the gateway, autoscaled separately from the LLMs |
| Multilingual corpus | bge-m3 or Qwen3-Embedding, both multilingual; evaluate on your languages |
| Huge corpora where storage cost dominates | Matryoshka truncation and/or vector quantization (Step 32), a smaller embedder |
| Highest precision on the final answer set | A stronger cross-encoder, or an LLM reranker on a short list |
| Strict data residency | Self-hosted models only, never hosted embedding APIs (embeddings can leak information about the original text) |

## Common mistakes

- **Forgetting the query instruction** (or adding it to documents too). Instruction-aware models quietly lose
  accuracy.
- **Mixing vectors from different models, revisions or dimensions in one index.** Searches return nonsense with no
  error.
- **Truncating Matryoshka vectors without re-normalising.** Cosine scores become wrong.
- **Chunks longer than the model limit,** silently cut off. Enforce a token limit in the chunker.
- **Reranking hundreds of candidates per query.** Latency explodes. Rerank a shortlist (20–100).
- **Comparing reranker scores across different queries, or treating them as probabilities.** They're only meaningful
  within one request.
- **Leaving TEI on its default `0.0.0.0`, or putting the API key on the command line.**

## Done when

- [ ] `text-embeddings-inference` is in the Brewfile and `text-embeddings-router --version` works
- [ ] Both models are downloaded, and `models.yaml` has their SHAs and the embedding contract
- [ ] `TEI_API_KEY` is in `secrets/dev.enc.env`; requests without it get **401**
- [ ] `embed_demo.py` shows instruction vs no-instruction, 256-dimension Matryoshka, and reranker scores, and you can
      explain the differences
- [ ] Embedding chunks/s and rerank latency (10 and 50) are recorded in `docs/benchmarks/models.md`
- [ ] `just search-models-up` then `just health` shows all four model servers ok
- [ ] `lsof` confirms 8083/8084 listen on `127.0.0.1`, and you've checked the metrics ports
- [ ] ADR-0008 and all files are merged through a PR

## Recap

> **RECAP**
> The search brain is now running:
>
> - an **embedder** that maps text into meaning space (with the right query instruction, Matryoshka sizes and a pinned
>   embedding contract)
> - a **reranker** that reads question and passage together to pick the best few
>
> Both are authenticated, batched, metered, natively accelerated and always on. With the LLMs from Step 7, all four
> model servers are ready. Step 9 puts the LiteLLM gateway in front of all of them, so the rest of the platform talks
> to one front door.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `bootstrap/Brewfile` (changed) | New "Embeddings & reranking (Step 8)" section installing `text-embeddings-inference`. |
| `infra/model-serving/models.yaml` (changed) | Inventory entries for the embedder (:8083) and reranker (:8084), with the embedder's embedding contract. |
| `scripts/model-path.sh` | Prints the local Hugging Face snapshot folder of a model (optionally an exact revision), or fails clearly. |
| `scripts/run-tei.sh` | Starts one TEI server on 127.0.0.1 with its own metrics port, the API key passed by environment from SOPS. |
| `scripts/install-tei-agents.sh` | Writes and loads the launchd agents `com.rag-platform.embedder` and `com.rag-platform.reranker`. |
| `bootstrap/home/Library/LaunchAgents/com.rag-platform.embedder.plist` | Reference copy of the generated embedder agent (example user `you`). |
| `bootstrap/home/Library/LaunchAgents/com.rag-platform.reranker.plist` | Reference copy of the generated reranker agent. |
| `justfile` (changed) | `embed_model` / `rerank_model` variables and `search-models-download`, `serve-embed`, `serve-rerank`, `search-models-up`, `search-models-down`, `health`, `embed-demo`, `bench-embed`. |
| `.env.example` (changed) | Documents the new `TEI_API_KEY` setting (no real value). |
| `scripts/new-dev-secrets.sh` (changed) | New dev secrets files now include a random `TEI_API_KEY` (`openssl rand -hex 24`). |
| `scripts/embed_demo.py` | The lesson demo: query instruction vs none, 256-dim Matryoshka, and reranker scores. |
| `scripts/bench_embeddings.py` | Measures embedding chunks/s (512 × ~200 tokens, batch 32) and rerank latency for 10 and 50 candidates. |
| `docs/benchmarks/models.md` (changed) | New "Embeddings and reranking" results table to fill in on the Mac. |
| `tests/test_tei_scripts.py` | Tests `model-path.sh`, `run-tei.sh` (stand-in `sops` and TEI: key only in the environment, exact flags) and `install-tei-agents.sh` (stand-in `launchctl`, plist contents), plus the reference plists. |
| `tests/test_embeddings_scripts.py` | Runs the demo and benchmark against a fake TEI server on 8083/8084 that enforces the bearer token. |
| `docs/adr/0008-serve-embeddings-and-reranking-with-tei-natively-behind-an-api-key.md` | ADR-0008: the decision, alternatives, consequences and when to revisit. |
| `docs/adr/README.md` (changed) | ADR-0008 added to the index. |
| `docs/steps/step-08-embedding-reranker-servers.md` | This write-up. |
| `docs/steps/README.md`, `docs/glossary.md`, `CHANGELOG.md` (changed) | Step index row, the new glossary terms, and the changelog entry. |

## Notes for this repository

- **Machine-specific values stay as placeholders.** The revision SHAs, the reranker's licence, the approver in
  `models.yaml`, and every number in the benchmark table can only come from your Mac after the download and the run.
  They are committed as the guide's `<…>` / `___` placeholders; fill them in on the Mac before merging. The reference
  plists use `REVISION_SHA` in the snapshot path for the same reason (angle brackets aren't valid inside a plist).
- **The API key.** The guide adds `TEI_API_KEY` by hand with `just secrets-edit`; do exactly that on an existing
  machine. So that a *fresh* setup also gets one, `scripts/new-dev-secrets.sh` now generates it, and `.env.example`
  lists its name. No real key is committed anywhere; the tests use an obviously fake low-entropy string.
- **A fix to `model-path.sh`.** The guide's version runs under `set -euo pipefail`. When a model was never downloaded,
  the `ls … | head -1` pipeline fails, and `pipefail` makes the script stop *silently* with exit code 2 instead of
  printing `not downloaded: <repo>`. A `|| true` (with a comment) lets it reach the clear message. A test covers both
  the "never downloaded" and the "wrong revision" cases.
- **Typing in the two Python scripts.** The guide's `post()` returns `object`, which strict mypy (Step 5) rejects as
  soon as the result is indexed (`post(...)[0]`). It returns `typing.Any` here instead; otherwise the scripts are the
  guide's code, reformatted by ruff (one end-of-line comment moved to its own line).
- **Extra `just` recipes.** Besides the guide's recipes, `search-models-download` (both `hf download` commands),
  `embed-demo` and `bench-embed` (the demo and the benchmark with the secrets decrypted) are small conveniences that
  run exactly the guide's commands.
- **Heredoc in `install-tei-agents.sh`.** The plist template is indented in the PDF; here it starts at column 0 so the
  `EOF` terminator is recognised and the XML is clean.
- **What was validated here (Linux, no Apple GPU, no Homebrew).** TEI was not run. Every TEI flag used (`--model-id`,
  `--hostname` default `0.0.0.0`, `--port`, `--prometheus-port` default `9000`, `--served-model-name`,
  `--json-output`, `--api-key` read from env `API_KEY`, `--auto-truncate` on by default) was confirmed in the
  `router/src/main.rs` of TEI's current source (Cargo version 1.9.4). The three shell scripts pass `bash -n` and are
  exercised by tests with stand-in `sops`, `text-embeddings-router` and `launchctl`; the plists parse with
  `plistlib`; `models.yaml` parses and the query instruction keeps its real `\n`; `just --dry-run` shows the expected
  commands; the demo and benchmark run end to end against a fake TEI server; ruff, strict mypy and the whole test
  suite pass. The Hugging Face Hub is not reachable from this container, so the SHAs could not be looked up.
