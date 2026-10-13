# Step 35 · RAG architectures: one slot, many designs

*Step 35 of 38 · Phase H · RAG core*

## At a glance

| | |
|---|---|
| **Goal** | Make the well-known RAG designs (naive, advanced, corrective, self-reflective, adaptive, agentic, graph and SQL RAG) available to every project as a one-word choice, all keeping the same guards, citations, memory, caching and audit, and compare them on the same questions. |
| **How, in one sentence** | The `pipeline` slot now holds an *architecture*: an object that decides how context is gathered (and whether an answer is reviewed), while the answer pipeline keeps doing everything else; `rag eval-answers` builds each architecture on the same profile and scores context recall, answers, citations, abstentions, groundedness, leaks and latency. |
| **Time** | About 4 hours. |
| **You'll end up with** | 8 architectures: naive, standard (advanced), corrective (CRAG), self-reflective (Self-RAG style), adaptive (Adaptive-RAG), agentic (iterative retrieval), graph (GraphRAG local search) and sql (structured RAG with read-only SQL under a database authorizer) · a graph store and an entity extractor that follow ingestion (added, replaced and deleted with their documents) · `rag eval-answers` and an answer gate in CI; sample tables for SQL RAG · a catalogue of further designs (multimodal, long-context, RAPTOR, GraphRAG global search, multi-agent, CAG…) with where each would plug in · 18 new tests; ADR-0035. |
| **New words** | RAG architecture, naive / advanced / modular RAG, corrective RAG, self-reflective RAG, adaptive RAG, query routing, multi-hop question, agentic RAG, ReAct, knowledge graph, entity, GraphRAG (local and global search), text-to-SQL, SQLite authorizer, context recall. |

## The big idea

> **ANALOGY · DIFFERENT DETECTIVES FOR DIFFERENT CASES**
> A police station doesn't send the same detective to every case.
>
> - A desk officer answers "what are your opening hours?" without opening a file (adaptive: no retrieval for
>   small talk).
> - A junior detective pulls the obvious file and reports (naive).
> - A senior detective checks several indexes, cross-references, and puts the best evidence first (standard).
> - A careful one throws out evidence that doesn't fit and looks again before reporting (corrective).
> - A self-critical one rereads the report against the evidence and redoes it if it doesn't hold up
>   (self-reflective).
> - An investigator follows leads one at a time: "that name leads to this company, which leads to…" (agentic).
> - An analyst works from the wall of connected names and photos (graph).
> - An accountant goes straight to the ledgers for "how much, how many" (SQL).
>
> Every one of them follows the same rules: same badge checks, same evidence log, same review before anything
> goes public. Only how they investigate differs.

### Eight architectures in one slot (Figure 109)

```
 naive                                         standard (advanced)
 question → vectors → top k → answer           transform → hybrid → fuse → rerank → tidy
 the baseline to beat                          the default (Steps 32–33)

 corrective (CRAG)                             self-reflective
 search → grade each chunk →                   answer → check support → search wider →
 keep / broaden / abstain                      answer again
 poor context never reaches the model          verified answers, more cost

 adaptive                                      agentic
 route: small talk · simple ·                  a model plans search → search → … → done
 compound (split)
 spend effort where it's needed                multi-hop questions

 graph (GraphRAG)                              sql (structured)
 entities + neighbours → more chunks, fused    a model writes read-only SQL → result is a source
 connected facts across documents              numbers and lists in tables

 All eight sit in one slot (pipeline: {use: …}). Guards, citations, memory, caching and the
 audit record are shared, so switching never removes a control.
 Conversational RAG, RAG-Fusion and HyDE are configurations of standard:
 memory + rewrite, multi-query + RRF, the hyde transformer.
```

Each architecture changes how context is gathered (and, for self-reflective, whether the answer is checked and
redone). Guards, citations, memory, caching and the audit record are shared. Conversational RAG, RAG-Fusion and
HyDE are configurations of standard, not separate architectures.

## What we're doing

1. Turn the pipeline slot into an architecture: `retrieve()` (how context is gathered) and `review()` (whether
   the answer is redone).
2. Build eight architectures, from the baseline to agentic, graph and SQL RAG.
3. Add a graph store and an entity extractor that follow every ingestion change.
4. Make SQL RAG safe: only reads of permitted tables, enforced by the database itself.
5. Compare architectures on the same questions, and gate CI on the default.

## Why we're doing this

> **WHY THIS MATTERS**
> "RAG" is not one design. The literature and the frameworks offer dozens, each solving a specific weakness of
> the simple version:
>
> - The simple version answers from whatever comes back, even when it's irrelevant (corrective RAG grades
>   first).
> - It never checks its own answer (self-reflective RAG does, and tries again).
> - It spends the same effort on "hi" as on a compound question (adaptive RAG routes).
> - It can't follow a chain of facts across documents (agentic and graph RAG can).
> - It's poor at numbers in tables: embeddings of CSV rows don't add up totals (SQL RAG asks the database).
>
> Teams usually pick one from a blog post and hard-code it. Here each is a component: a project picks by
> configuration, measures with one command, and switches without touching code, and without losing a single
> control.

| Need | How this step meets it |
|---|---|
| A baseline to measure against | `naive` |
| The robust default | `standard` (Steps 32–33) |
| Don't answer from bad context | `corrective`: grade, keep, broaden or abstain |
| Check answers before showing them | `self-reflective`: groundedness check, wider search, regenerate, keep the better |
| Right effort per question | `adaptive`: no retrieval for small talk, split compound questions |
| Multi-hop questions | `agentic` (a model plans searches) and `graph` (entities link chunks) |
| Tables and numbers | `sql`: read-only SQL on permitted tables, result cited like a document |
| Same controls everywhere | Architectures only gather context; guards, citations, memory, cache and audit stay in the shared pipeline |
| Choose with evidence | `rag eval-answers`: context recall, answers, citations, abstentions, groundedness, leaks, latency |

> **IN A COMPANY**
> Architecture choices show up in risk reviews as "how does the system decide what to show the model, and what
> happens when it's wrong?". Being able to answer "we use corrective RAG for policy questions because irrelevant
> context caused confident wrong answers in testing; here are the numbers" is the difference between a design
> decision and a guess. The same comparison, rerun on each release, is evidence of ongoing monitoring (NIST AI
> RMF "Measure", ISO/IEC 42001 performance evaluation).

## Key ideas

| Term | Plain-English meaning |
|---|---|
| **Naive RAG** | Embed the question, take the top k most similar chunks, answer. The baseline. |
| **Advanced / modular RAG** | Naive plus improvements before retrieval (query rewriting), during (hybrid, fusion) and after (reranking, filtering); built from swappable modules. |
| **Corrective RAG (CRAG)** | Grade each retrieved chunk; use only relevant ones; search differently, or abstain, if none are. |
| **Self-reflective RAG (Self-RAG)** | The system critiques its own answer against the sources and retrieves/regenerates if it falls short. |
| **Adaptive RAG, query routing** | Choose a strategy per question: no retrieval, single search, or multi-step. |
| **Multi-hop question** | One that needs two or more facts found in different places, in sequence. |
| **Agentic RAG, ReAct** | A model decides, step by step, which tool to use next (here: which search), reasoning from what it has found. |
| **Knowledge graph, entity** | A map of named things (systems, policies, error codes) and how they're connected. |
| **GraphRAG** | Using a knowledge graph to find related information: *local* search follows entities near the question; *global* search summarises whole communities of entities. |
| **Text-to-SQL** | A model writes a database query from a question. |
| **SQLite authorizer** | A callback SQLite runs for every action a statement wants to take; here it allows only reading the permitted tables. |
| **Context recall** | The share of the right documents that actually reached the model: what architectures change. |

> **IN PLAIN ENGLISH**
> Until now, "how do we find the context?" was fixed: Step 32's search. This step makes that question a
> setting. The rest of the answer pipeline (guards, packing the context, the model, checking citations,
> memory, cache, audit) doesn't care which detective found the evidence.

## How to do it

All commands run from the repository root (`~/dev/rag-platform/` in the guide) on your Mac, with uv as in
earlier steps.

### 1 · Architectures

**File · `libs/rag-core/src/rag_core/components/architectures.py`** holds all eight. Two methods are the whole
contract:

```python
class Standard:
    name = "standard"
    reviews = False   # True: may replace the first answer, so it is never streamed as a draft

    def retrieve(self, pipe, query) -> Retrieval:        # the chunks (or a direct answer)
        r = pipe.search.search(query)
        return Retrieval(r.hits, r.trace)

    def review(self, pipe, query, answer, context, trace, post_check) -> Answer:
        return answer                                     # may replace an answer
```

`Retrieval` carries the hits, an `info` dict that becomes the answer trace's `search` entry, and an optional
`direct` answer (adaptive's reply to "hello"). Each architecture is registered for the `pipeline` slot, with
its own parameters on top of Step 33's `AnswerParams` (`search_k`, `abstain_without_hits`, `uncited`,
`abstain_text`, `history_turns`, `blocked_text`, `stream`):

| Name | Class | Extra parameters (defaults) | Status |
|---|---|---|---|
| `standard` | `Standard` | – | live |
| `naive` | `Naive` | – | live |
| `corrective` | `Corrective` | `grader: auto` (auto · score · lexical · llm), `min_relevance: 0.25`, `min_coverage: 0.34`, `broaden_factor: 3`, `llm_slot: judge_llm` | live |
| `self-reflective` | `SelfReflective` | `max_rounds: 2`, `min_support: 0.5`, `widen_factor: 2` | live |
| `adaptive` | `Adaptive` | `router: heuristic` (or `llm`), `greeting_reply`, `max_parts: 3`, `llm_slot: llm` | live |
| `agentic` | `Agentic` | `max_steps: 4`, `llm_slot: llm` | mocked (needs a model) |
| `graph` | `Graph` | `neighbours: 2`, `max_graph_chunks: 8` (needs `graph_store`) | live |
| `sql` | `SqlRag` | `tables` (required), `llm_slot: llm`, `max_rows: 50`, `max_steps: 200000`, `with_documents: true` | mocked (needs a model) |

The same file adds a `graph_store` component (`memory`: `MemoryGraphStore`) and an enricher
(`graph-entities`: `EntityExtractor`).

> **READING THE ARCHITECTURES**
>
> - **naive** deliberately skips rewriting, keyword search, reranking and post-processing, but still only sees
>   permitted chunks. It asks the vector store for exactly `k` chunks (keyword index if there is no vector store).
> - **corrective** grades with the cheapest signal available: the reranker's 0–1 relevance if Step 32's reranker
>   ran, otherwise word coverage (the share of the question's content words found in the chunk), or an LLM
>   yes/no if configured. Nothing relevant → one broader keyword search (`k × broaden_factor` candidates) →
>   still nothing → an empty list, which the shared pipeline turns into "I don't know" without a model call.
>   The trace says which: `action: correct | broadened | abstain`.
> - **self-reflective** uses Step 34's groundedness check as its critic (unsupported sentences, numbers that
>   aren't in the sources; an abstention counts as 100 problems), widens the search (k × 2, plus keyword search
>   on the original words), goes back through `context_for` (post-check and context guards included),
>   regenerates, and keeps whichever answer has fewer problems. The rounds are in `trace.reflection`.
> - **adaptive** routes with a cheap heuristic (a greeting pattern; "… and how/what/when …" splits) or a model.
>   A compound question searches each part and guarantees each part's best chunk a place in the context, then
>   fills the rest from the parts' results fused by RRF.
> - **agentic** shows the model only titles and sections of what it has found (as data inside `<found>`), never
>   the text, and asks for one JSON action: `{"search": "…"}` or `{"done": true}`. Every search it requests runs
>   as the person through the normal search pipeline; repeated searches end the loop, `max_steps` bounds it, and
>   if the planner fails it falls back to one standard search.
> - **graph** has three parts: an entity extractor (an enricher at ingestion), a graph store (entities, chunks,
>   co-occurrence), and retrieval that adds chunks for the question's entities (score 1.0 per entity) and their
>   nearest neighbours (0.3), fused by RRF with the standard search. Graph hits are access-checked like any other.
> - **sql** describes only tables this person may see, asks for one `SELECT`, and runs it under an authorizer:
>   SQLite itself refuses writes, `ATTACH`, `PRAGMA`, `sqlite_master` and other tables. A step limit stops
>   runaway queries, a row limit caps output. Any failure (bad SQL, refused SQL, "NONE", no model) falls back to
>   documents. The result becomes a chunk with the URI `sql://<table>`, the table's access, and the SQL in its
>   metadata, so it is cited like a document.

**Entities.** The offline extractor finds error and policy codes (`E-4021`, `POL-117`, `SEV1`), acronyms
(`MFA`, `VPN`), Title Case phrases (`Self Service`, `Okta Verify`) and an optional list of your own terms
(`terms: [Navan]`). Entities are stored lower-case with punctuation removed (`E-4021` → `e 4021`). Every pair of
entities in the same chunk becomes a link, counted, so "neighbours" are the entities most often mentioned
together.

**SQL safety in layers.** Before SQLite sees the statement, the code requires a single statement starting with
`SELECT` or `WITH`. Then the authorizer callback allows only `SELECT`, `READ`, `FUNCTION` and `RECURSIVE`
actions, and `READ` only for the visible tables. Then a progress handler stops the query after `max_steps`
virtual-machine steps, and `fetchmany(max_rows)` caps the rows. The tables are CSV files loaded into an
in-memory database; table names must be lower-case identifiers, column names are reduced to letters, digits and
`_` (`Limit (AUD)` → `limit_aud`), and values are inserted as parameters.

### 2 · The answer pipeline, refactored

**File · `libs/rag-core/src/rag_core/answer.py` (changed).** The pipeline builds the architecture from the
`pipeline` slot (Standard with default settings if there is none) and asks it for context. Two new public
methods give architectures that retrieve again the same path back in:

```python
def context_for(self, query, hits, post_check, trace_data) -> tuple[PackedContext | None, Answer | None]:
    """Post-check, context guards, abstain-if-empty, pack. Architectures that retrieve again
    (self-reflective) come back through here, so no check is ever skipped."""

def generate(self, query, context, trace_data) -> Answer:
    """Generate and check one answer (citations, output guards). Not remembered or cached yet:
    a reviewing architecture may still replace it."""
```

`answer()` now reads: prepare (memory, input guards, cache, `arch.retrieve`, `context_for`) → `generate` →
`arch.review` (unless blocked) → remember and cache once → return. `stream()` does the same for an architecture
with `reviews = True`: it generates, reviews, and sends one checked text, never the first draft. The trace gains
`architecture` (its name), `search` (the architecture's own info) and `context.documents` (the documents that
reached the model, which `rag eval-answers` uses for context recall).

> **WHY THE REFACTOR MATTERS**
> Before, `_prepare` did search, post-check, guards and packing in one go. Now `context_for` is a separate door
> that every retrieval goes through, including a self-reflective second round. Memory and cache are written
> once, after any review, so a draft that gets replaced is never remembered or cached.

**File · `libs/rag-core/src/rag_core/components/generation.py` (changed).** The Step 33 registration of
`pipeline: standard` (which returned bare `AnswerParams`) moved to `architectures.py`, where it now builds a
`Standard` architecture.

**File · `libs/rag-core/src/rag_core/ingest.py` (changed): the graph follows its documents.**

```python
# Step 35: GraphRAG's entity store is one more place a document lives
self.graph = container.get("graph_store") if container.has("graph_store") else None
...
if self.graph is not None:  # before enrichers re-add this source's entities
    self.graph.delete_document(source.uri)
for e in self.enrichers:
...
n = self._delete_everywhere(uri)
self._forget_graph(uri)
```

A replaced document's old chunks leave the graph before the enricher adds the new ones; a deleted document
leaves the graph as well as the vector and keyword stores.

### 3 · Compare them

**File · `examples/eval/handbook.yaml` (changed)** gains an `architectures:` section, merged on top of the
chosen profile exactly like Step 32's `variants:`:

```yaml
# Architectures (Step 35): `rag eval-answers` builds each one on the same profile and questions.
architectures:
  naive:            {pipeline: naive}
  standard:         {pipeline: standard}
  corrective:       {pipeline: corrective}
  self-reflective:  {pipeline: self-reflective}
  adaptive:         {pipeline: adaptive}
  graph:            {pipeline: graph, graph_store: memory, enrichers: [context-header, graph-entities]}
```

**File · `libs/rag-core/src/rag_core/evaluate.py` (changed)** adds `AnswerScores`, `run_answers` and
`format_answer_table`. For every question, as the dataset's person, the whole answer pipeline runs (follow-up
questions get their history in conversation memory first), and:

| Metric | Meaning |
|---|---|
| `context_recall` | Share of the right documents that reached the model (what architectures change) |
| `answered` | Answerable questions that got an answer (not "I don't know", not blocked) |
| `cite_hit` | Answerable questions whose answer cites a right document |
| `abstain_ok` | Unanswerable questions (no relevant document) answered "I don't know" |
| `grounded` | Answers the groundedness guard didn't flag |
| `leaks` | Forbidden documents cited |
| `p50_ms` | Median time per answer |

**File · `libs/rag-core/src/rag_core/cli.py` (changed)** adds `rag eval-answers dataset.yaml [--file rag.yaml]
[--profile p] [--variant name …] [--no-ingest] [--fail-under METRIC=VALUE …] [--json]`. Any leak fails the run.

```bash
uv run rag eval-answers examples/eval/handbook.yaml --profile offline
```

Output in this repository (the sample handbook here differs from the guide's, so the numbers do too):

```
25 questions, profile 'offline'

architecture           ctx recall  answered  cite hit  abstain ok  grounded  leaks  p50 ms
------------------------------------------------------------------------------------------
naive                       0.854     0.833     0.833       1.000     1.000      0     2.8
standard                    1.000     0.917     0.917       1.000     1.000      0     8.2
corrective                  0.979     0.917     0.917       1.000     1.000      0     7.2
self-reflective             1.000     0.917     0.917       1.000     1.000      0     8.7
adaptive                    1.000     0.917     0.917       1.000     1.000      0     9.4
graph                       1.000     0.917     0.917       1.000     1.000      0     9.6
```

The guide's run (on its own handbook) showed the same shape: naive 0.771 context recall, standard and the
architectures built on it 1.000, corrective 0.917 (its grading dropped some right chunks), every architecture
the same "answered" rate, no leaks.

> **WHAT THESE NUMBERS CAN AND CAN'T TELL YOU**
> They can: naive retrieval loses a share of the right documents that standard search finds (15% here, 23% in
> the guide); corrective grading at its default threshold drops some good chunks too; no architecture leaks;
> adaptive and self-reflective cost a little more time.
>
> They can't: compare answer quality. Offline, every architecture hands its context to the extractive generator,
> which can't paraphrase, so "answered" is stuck at the same value for all of them. Self-reflective's second
> round and agentic's planning need a real model to show their value. Run
> `rag eval-answers … --profile local --no-ingest` (with the handbook ingested) to compare them with Qwen, and
> add the architectures that need a model to the file once you do.

**File · `justfile` (changed):** `ci-config` gains `just answer-eval`, and the recipe:

```just
# Architecture gate (Step 35): the default architecture puts the right documents in front of the
# model and says "I don't know" when it should, with no forbidden document cited
answer-eval *args:
    uv run rag eval-answers examples/eval/handbook.yaml --profile offline --variant standard --fail-under context_recall=0.95 --fail-under abstain_ok=1 {{args}}
```

**File · `rag.yaml` (changed):** a comment above `pipeline:` in the `offline` profile lists the eight
architectures and what `graph` and `sql` need. Switch without editing the file with
`RAG__PIPELINE__USE=adaptive`.

### 4 · See them work

**Adaptive: small talk and a compound question.**

```bash
RAG__PIPELINE__USE=adaptive uv run rag ask "Hi!" \
  "What is the international per diem and how long do I have to claim expenses?" \
  --no-memory --profile offline --group all-staff --corpus examples/eval/handbook.yaml --json
```

Summarised from the JSON trace:

```
Q: Hi!
   route: greeting     parts: None
   context documents: []
   A: Hello! Ask me about company policies, IT or HR, and I'll answer from our documents.
Q: What is the international per diem and how long do I have to claim expenses?
   route: compound     parts: ['What is the international per diem', 'how long do I have to claim expenses']
   context documents: ['annual-leave-2021.md', 'annual-leave.md', 'expenses.md', 'parental-leave.md',
                       'remote-work.md', 'security-passwords.md', 'travel.md']
   A: The international per diem is 150 dollars a day [doc 1].
```

> **READING IT**
> "Hi!" got a reply with no retrieval and no model call. The compound question was split, and both `travel.md`
> and `expenses.md` reached the context; the extractive generator then quoted only the best-matching sentence.
> An LLM generator answers both parts from the same context.

**Graph: entities bring in related chunks.**

```bash
RAG__PIPELINE__USE=graph RAG__GRAPH_STORE__USE=memory RAG__ENRICHERS='[context-header, graph-entities]' \
  uv run rag ask "What does Okta Verify do?" --no-memory --profile offline --group all-staff \
  --corpus examples/eval/handbook.yaml --json
```

```
Q: What does Okta Verify do?
   entities: ['okta verify']   related: ['mfa', 'sms']   graph hits: 2
   context documents: ['ai-usage.md', 'annual-leave.md', 'security-passwords.md', 'travel.md',
                       'vpn-troubleshooting.md']
   A: Approve the Okta Verify push within 60 seconds of connecting; if it keeps failing, check your phone's
      date and time settings [doc 1]. Use the Okta Verify app or a hardware security key [doc 2].
      [doc 1] vpn-troubleshooting.md   [doc 2] security-passwords.md
```

> **READING IT**
> The question names one entity, `okta verify`; the graph knows it's mentioned alongside `mfa` and `sms`, and
> adds the chunks that mention them. The answer draws on both the VPN page and the password policy.

**`uv run rag components --kind pipeline`** now lists eight architectures with their parameters (adaptive,
agentic *mocked*, corrective, graph, naive, self-reflective, sql *mocked*, standard).

The agentic and SQL architectures need a model to plan searches or write SQL, so here they're shown by their
tests (with a scripted model); with the `local` profile they use `qwen-fast` through the gateway.

**Example · SQL RAG in a profile:**

```yaml
pipeline:
  use: sql
  llm_slot: llm
  max_rows: 50
  tables:
    expense_limits: {path: /data/expense_limits.csv, description: "spending limits by category", groups: [all-staff]}
    salary_bands:   {path: /data/salary_bands.csv, classification: confidential, groups: [hr]}
```

The sample tables are in `examples/tables/` (`expense_limits.csv`, `salary_bands.csv`).

### 5 · Test it

**File · `libs/rag-core/tests/test_architectures.py`** (18 tests, counting the six SQL authorizer cases).

```bash
just audit-test          # everything, with the throwaway Postgres
just answer-eval
```

> **WHAT THE TESTS PROVE**
>
> - naive uses vectors only; corrective drops off-topic chunks, abstains on an unanswerable question after
>   broadening, and can grade with a model.
> - self-reflective replaces an answer with a wrong number by a supported one, and streams only the checked text.
> - adaptive answers small talk without retrieval, splits a compound question so both documents reach the model,
>   and can route with a model.
> - agentic runs the searches a (scripted) planner asks for, shows it only titles as data, and falls back when
>   the planner fails.
> - graph extracts entities, follows deletions, adds related chunks, and never returns a chunk the person can't
>   see even though its entities are in the graph.
> - sql answers from a table with a citation, never describes a table the person can't see, and the authorizer
>   refuses six kinds of dangerous SQL; bad SQL falls back to documents.
> - Every architecture keeps the guards: an injection attempt is blocked whichever one is configured.

### 6 · Record the decision

**File · `docs/adr/0035-rag-architectures-as-switchable-pipelines.md`**: the `pipeline` slot holds an
architecture with two hooks; the answer pipeline keeps every control for all of them; `rag eval-answers`
compares them and CI gates the default. Alternatives considered: one fixed architecture, LangGraph / LlamaIndex
workflows per project, Microsoft GraphRAG as the graph design, text-to-SQL with database grants only. Revisit
when agent workflows need tools beyond search and SQL, a persistent graph store is needed (Neo4j, Apache AGE in
Postgres), or global (community-summary) graph search is required.

## Benefits

- One word to change design, with the same controls and records.
- Evidence for the choice: the same questions, the same metrics, every architecture.
- Safe structured answers: SQL that can only read what the person may see.
- Connected knowledge: entities link chunks that similarity alone ranks apart.
- Honest failure: corrective and self-reflective designs prefer "I don't know" to confident answers built on
  poor context.

## Drawbacks and risks

- Cost and latency grow with sophistication: self-reflective may generate twice; agentic calls a model per
  step; LLM grading calls a model per chunk.
- Heuristic routing and grading misfire: a compound split can break a question in the wrong place; a lexical
  grader can drop a right chunk (it did here). Tune with evaluation.
- Text-to-SQL can be wrong without being dangerous: the authorizer stops harm, not a wrong `WHERE`. Show the SQL
  with the answer (it's in the chunk's metadata) for anything that matters.
- The graph is only as good as the entities: the offline extractor finds codes, acronyms and Title Case
  phrases; real GraphRAG extracts entities and relations with a model.
- Agents can wander: step limits, repeated-query detection and the fallback keep them bounded.

> **WATCH OUT**
> The in-memory graph store lives in one process. An API replica that didn't do the ingestion has an empty
> graph, so `graph` quietly behaves like `standard` there. Production needs a persistent graph store.

## Alternatives: the wider catalogue

| Design | What it does | Where it plugs in here |
|---|---|---|
| Conversational RAG | Rewrites follow-ups using the chat history | `standard` + memory + rewrite (Steps 32–33) |
| RAG-Fusion | Several paraphrases, results fused by RRF | `standard` + multi-query |
| HyDE | Searches with a hypothetical answer | `standard` + hyde |
| Sentence-window / small-to-big | Match small, read big | chunkers + window-expand / parent-expand (Steps 31–32) |
| Long-context RAG / CAG | Put whole documents (or a cached corpus) in a long context window | parent-expand + a large budget; or skip retrieval for tiny corpora |
| RAPTOR | A tree of recursive summaries, searched at several levels | An enricher writing summary chunks + `standard` |
| GraphRAG global search (Microsoft) | Community summaries answer "what are the main themes?" | A batch job writing community-summary chunks; the graph slot for local search |
| LightRAG / HippoRAG | Lighter graph indexes; personalised PageRank over entities | Alternative `graph_store` and graph scoring |
| Multimodal RAG (images, charts, slides) | Captions or image embeddings make figures searchable | Docling/VLM enricher writing caption chunks (Step 7's mlx-vlm); ColPali-style page embeddings as a vector store |
| Table QA over many tables | Schema retrieval before text-to-SQL | A schema-search step in `sql` |
| Multi-agent RAG | Specialist agents (HR, IT, finance) behind a router | `adaptive` routing to per-domain profiles/collections |
| Federated RAG | Several sources (wiki, tickets, CRM) searched and fused | Several retrievers + RRF; per-source access in each store |
| Speculative RAG / REPLUG / Fusion-in-Decoder | Research designs combining several drafts or models | Architecture plugins via entry points (Step 30) |
| LangGraph, LlamaIndex Workflows, Haystack pipelines, DSPy | Frameworks for composing these | Wrap as an architecture plugin; keep rag-core's controls around it |

> **TIP**
> A project's own architecture is just another component: a class with `name`, `reviews`, `params`,
> `retrieve()` and `review()`, registered with `@register("pipeline", "my-design", params=…)` in a package that
> exposes a `rag_core.components` entry point (Step 30). It inherits every control.

## Which approach fits which situation

A quick way to pick a starting architecture (Figure 111): answer the questions from the top; the first yes wins.

```
Small talk, greetings, thanks?                          → adaptive
Numbers, totals, lists that live in tables?             → sql (+ documents)
Needs facts from several places, in steps?              → agentic, or graph if entities connect them
Wrong context is worse than no answer?                  → corrective
Every answer must be checked before it's shown?         → self-reflective (+ stream: checked)
Otherwise                                               → standard

Then measure: rag eval-answers runs each candidate on the same questions
(context recall, answered, citations, abstentions, leaks, latency).
```

| Situation | Best choice |
|---|---|
| A new project, unknown traffic | `standard`; measure against `naive` to prove the extras pay |
| Policy or compliance answers where wrong context is dangerous | `corrective` (+ `uncited: abstain`) |
| Customer-facing answers that must be verified | `self-reflective` + `stream: checked` |
| Chat assistant with lots of small talk and mixed questions | `adaptive` |
| Investigations across many documents ("which systems did the 2024 incident touch?") | `agentic`, or `graph` if entities are well defined |
| Spending limits, headcounts, prices in tables | `sql` with `with_documents: true` |
| A tiny corpus (a few documents) | Long-context: skip retrieval or retrieve whole documents |

## Common mistakes

- Choosing an architecture from a benchmark on someone else's data.
- Building a new pipeline for an architecture and forgetting the guards, post-check or audit in it.
- Text-to-SQL with a database login that can read everything "because the prompt says only these tables".
- Agent loops without step limits or fallbacks.
- Streaming the first draft of a self-reflective answer.
- Graphs that aren't updated when documents change.

## Done when

- [ ] `uv run rag components --kind pipeline` lists eight architectures
- [ ] `uv run rag eval-answers examples/eval/handbook.yaml --profile offline` shows naive behind standard on
      context recall, and 0 leaks
- [ ] The adaptive and graph examples show their routes and entities in the trace
- [ ] `just answer-eval` passes
- [ ] With the platform up: you ran `rag eval-answers … --profile local --no-ingest` and chose the architecture
      for your first project from the numbers
- [ ] `just audit-test` passes
- [ ] ADR-0035 is committed

## Recap

> **RECAP**
> The platform now offers the main RAG designs as configuration:
>
> - naive and standard to measure against each other
> - corrective and self-reflective for answers that must rest on good evidence
> - adaptive to spend effort where it's needed
> - agentic and graph for multi-hop questions, sql for tables, safely
> - one comparison command and a CI gate, with every control shared by all of them
>
> That completes Phase H, the RAG core. Next, Phase I · Production & reuse, starting with Step 36: the data
> lifecycle (retention, erasure, re-indexing without downtime, backups), the STRIDE threat model, C4 diagrams
> and the mapping of every control to NIST AI RMF, ISO/IEC 42001, the EU AI Act and the Australian Privacy
> Principles.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `libs/rag-core/src/rag_core/components/architectures.py` | The eight architectures (`Standard`, `Naive`, `Corrective`, `SelfReflective`, `Adaptive`, `Agentic`, `Graph`, `SqlRag`), `Retrieval`, `split_compound`, the `memory` graph store and the `graph-entities` enricher |
| `libs/rag-core/src/rag_core/answer.py` (changed) | The pipeline asks the architecture for context; new `context_for()` and `generate()`; review before memory/cache; reviewing architectures never stream a draft; `architecture` and `context.documents` in the trace |
| `libs/rag-core/src/rag_core/components/generation.py` (changed) | The old `pipeline: standard` registration moved to `architectures.py` |
| `libs/rag-core/src/rag_core/ingest.py` (changed) | The graph store loses a document's chunks when it is replaced or deleted |
| `libs/rag-core/src/rag_core/evaluate.py` (changed) | `AnswerScores`, `run_answers`, `format_answer_table`; `variant_configs` can read the `architectures:` section |
| `libs/rag-core/src/rag_core/cli.py` (changed) | `rag eval-answers` with `--variant`, `--no-ingest`, `--fail-under`, `--json` |
| `libs/rag-core/tests/test_architectures.py` | 18 tests: each architecture, the graph following ingestion, the SQL authorizer, the comparison, guards kept |
| `examples/eval/handbook.yaml` (changed) | The `architectures:` section compared by `rag eval-answers` |
| `examples/tables/expense_limits.csv`, `examples/tables/salary_bands.csv`, `examples/tables/README.md` | Sample tables for SQL RAG (one for all staff, one confidential to HR) |
| `examples/corpus/handbook/exec-compensation.md` (changed) | One sentence naming the Remuneration Committee, so the graph access test has a restricted entity to find |
| `rag.yaml` (changed) | A comment listing the architectures that can fill `pipeline`, and what graph and sql need |
| `justfile` (changed) | `answer-eval` recipe, run by `ci-config` |
| `docs/adr/0035-rag-architectures-as-switchable-pipelines.md` | ADR-0035 |
| `docs/glossary.md`, `docs/adr/README.md`, `docs/steps/README.md`, `CHANGELOG.md` (changed) | New terms, indexes, changelog |

## Notes for this repository

- **Code reconstructed from the PDF.** The listings' indentation and line wraps were rebuilt; `ruff format`
  re-wrapped a few long lines. The guide shows only the changed parts of `answer.py`, `ingest.py`, `evaluate.py`
  and the justfile; the rest (the `_prepare` that calls `arch.retrieve`, `_finish` without memory writes, the
  streaming path for reviewing architectures, and the `rag eval-answers` command) was written here to match.
- **Corrective's default threshold is 0.25, not the guide's 0.15.** This repository's offline `term-overlap`
  reranker (Step 32) gives 0.15–0.2 to passages that share only common words with the question, so at 0.15
  "What is the cafeteria menu on Fridays?" kept irrelevant chunks instead of abstaining. At 0.25 the test
  behaves as the guide describes and corrective's context recall is 0.979 (the guide's was 0.917).
- **Two small robustness changes.** Adaptive de-duplicates the "best chunk of each part" list (two parts can share
  a best chunk), and the graph store's `entities_in` ignores entities whose chunks have all been deleted.
- **SQL test numbers.** The guide's per-diem example uses AUD 95/140; the sample handbook here says 90/150
  dollars, so `examples/tables/expense_limits.csv` matches the handbook and the SQL test's scripted answer says
  150. The table's first two rows by name are still "Client meal" and "Conference ticket", as the authorizer
  test expects.
- **Test count.** The guide says 19 new tests (453 in total); this repository adds 18 (13 test functions, one
  of them parametrised six ways), and its total differs because earlier steps here added their own tests. The
  full suite passes: 669 passed, live-service tests skipped.
- **What was validated here.** ruff, ruff format, strict mypy, the full pytest suite; `rag eval-answers` on the
  offline profile (table above); `just answer-eval`, `just search-eval` and `just guard-eval` (the corpus change
  doesn't move their numbers); `rag config validate` for all three profiles; `rag components --kind pipeline`
  (eight entries); the adaptive and graph `rag ask` examples. The `--profile local` comparison needs the models,
  LiteLLM, Postgres and Valkey running and was not run here.
