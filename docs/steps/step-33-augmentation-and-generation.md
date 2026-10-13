# Step 33 · Augmentation and generation: cited answers

*Step 33 of 38 · Phase H · RAG core*

## At a glance

| | |
|---|---|
| **Goal** | Turn the chunks from Step 32 into an answer a person can trust: grounded in the documents they may see, with a citation after every claim, an honest "I don't know" when the documents don't say, follow-up questions that work, streaming, and a record of everything, behind `/v1/answer`. |
| **How, in one sentence** | An answer pipeline in rag-core (memory → guards → cache → search → abstain → context → generate → cite → guards) where the context builder, generator, memory and cache are switchable components, and rag-api serves it with the same token, policy and audit rules as search, recording the audit event before anything is handed out. |
| **Time** | About 3 hours. |
| **You'll end up with** | A context builder: numbered `<doc id="n">` blocks within a token budget; relevance, "lost in the middle" or document order; optional sentence compression; documents that can't forge other documents · citation checking: markers that point at nothing are removed and counted; uncited answers kept, flagged or turned into abstentions · two generators: the registered prompt (Step 24) on the answer model, streamed; and an extractive no-model fallback · abstention without a model call when nothing relevant is found · conversation memory (process or Valkey), per person and session, expiring · three answer caches (exact in process, exact in Valkey, semantic), keyed by who can see what and invalidated by every ingestion change · `rag ask` (with follow-ups and streaming); rag-api's `/v1/answer` (JSON or server-sent events) and `/v1/feedback`; OPA actions `answer` and `feedback` · 28 new tests; ADR-0033. |
| **New words** | augmentation, grounding, context window, token budget, context packing, lost in the middle, context compression, citation, attribution, abstention, hallucination, streaming, server-sent events, conversation memory, exact cache, semantic cache, cache invalidation, epoch, time to first token. |

## The big idea

> **ANALOGY · AN OPEN-BOOK EXAM WITH A STRICT EXAMINER**
> The model sits an open-book exam: it may answer only from the pages in front of it.
> - The invigilator chooses the pages (Step 32), numbers them, and checks the student is allowed to see each
>   one.
> - The desk is small (the context window): only so many pages fit, so the best go on top.
> - Every claim needs a page number. The examiner crosses out references to pages that weren't on the desk,
>   and marks down an answer with no references at all.
> - "The pages don't say" is a good answer. Making something up is the worst one.
> - The exam office keeps a register: who sat which paper, with which pages, under which rules, before the
>   results go out.
>
> That's augmentation and generation: add the right material to the question, let the model write, then check
> what it wrote against what it was given.

### The answer pipeline (Figure 104)

```
 memory                      input guards              cache                          search
 earlier turns, this person  Step 34: injection,       same access + question         Step 32's pipeline
 + this session only    →    PII, topics          →    + index epoch + prompt    →    + OPA post-check
                                                                                           ↓
 cite + output guards        generate                  context                        abstain?
 keep valid [doc n] only; ←  registered prompt,   ←    <doc id=n> blocks          ←   nothing relevant:
 flag uncited; Step 34       answer model, streamed    within a token budget          "I don't know", no model

 then: remember the turn, cache the answer, return it with citations, usage, model, prompt version and timings
 rag-api records the audit event BEFORE handing anything out (streaming: after search, before the first word)
```

Memory gives follow-ups their meaning; input guards (Step 34) run before anything is spent; the cache
answers repeats; search runs as the person, with OPA's post-check; with nothing relevant the pipeline
abstains without a model call; otherwise the context is packed, the registered prompt is sent to the answer
model (streamed), citations are checked and output guards run. rag-api records the audit event before
anything is handed out.

## What we're doing

1. Pack the context: number the chunks, fit them in a token budget, order them, keep documents from forging
   each other.
2. Generate with the registered answer prompt (Step 24) on the answer model, whole or streamed.
3. Check citations against what was shown; decide what to do with an answer that cites nothing.
4. Abstain when retrieval finds nothing, without paying for a model call.
5. Remember the conversation per person and session; cache answers safely.
6. Serve it as `/v1/answer` (JSON or a live stream) and collect `/v1/feedback`, with policy and audit exactly as
   for search.

## Why we're doing this

> **WHY THIS MATTERS**
> A model handed five chunks and a question will happily write a fluent answer whether or not the chunks
> contain it. The failures are well known:
> - **Hallucination:** the documents don't say, the model fills the gap. Fix: an explicit abstention
>   instruction, abstaining when retrieval finds nothing, flagging uncited answers.
> - **Unverifiable answers:** no way to check where a claim came from. Fix: numbered sources and citation
>   checking.
> - **Lost in the middle:** models attend best to the start and end of a long context. Fix: a budget, and
>   ordering options.
> - **Prompt injection through documents:** a document containing "ignore your instructions" or a fake
>   `</doc>`. Fix: documents are data inside tags they can't close (Step 24), and Step 34's guards.
> - **Follow-ups that fail:** "can I take it in two blocks?" means nothing on its own. Fix: memory plus query
>   rewriting.
> - **Cost and latency:** the same question asked a hundred times a day. Fix: caching, without ever sharing
>   answers across permission boundaries.

| Need | How this step meets it |
|---|---|
| Answers only from permitted documents | Search as the person (Step 32) + OPA post-check before the context is built |
| Every claim traceable | `<doc id="n">` sources, `[doc n]` markers, invalid markers removed, citations returned with document ids |
| No invented answers | Abstain on no hits (no model call), "I don't know" in the prompt, uncited answers flagged or abstained |
| Fits the model | Token budget, per-chunk cap, three orderings, optional compression |
| Conversations | Memory per person + session (process or Valkey, TTL), with Step 32's `rewrite` / `with-history` |
| Fast and cheap for repeats | Exact and semantic caches keyed by access fingerprint, prompt, model, settings and index epoch |
| Feels fast | Server-sent events: the first words arrive while the rest is generated |
| Accountable | Audit event before any text is sent: who, which documents, which prompt and model, outcome, tokens. Never the text. |
| Learns from users | `/v1/feedback`: thumbs up/down with a fixed reason list, tied to the answer's trace |

> **IN A COMPANY**
> Regulators and customers increasingly expect AI answers to be attributable (EU AI Act transparency duties,
> ISO/IEC 42001's traceability, NIST AI RMF's "explainable and interpretable"). In practice that means: show
> sources, say "I don't know", log which sources and which model and prompt version produced each answer,
> keep personal data out of logs, and collect user feedback as evidence of monitoring. This step builds each
> of those in, and Step 36 maps them to the frameworks.

## Key ideas

| Term | Plain-English meaning |
|---|---|
| Augmentation, grounding | Adding retrieved documents to the prompt so the model answers from them, not from memory. |
| Context window, token budget | How much text a model can read at once; the share of it we give to documents. |
| Context packing | Choosing which chunks fit the budget and in what order. |
| Lost in the middle | Models notice the start and end of a long context more than the middle; putting the best chunks at both ends helps. |
| Context compression | Keeping only the sentences that matter, so more sources fit. |
| Citation, attribution | Saying which source each claim came from, so a person can check it. |
| Abstention | Saying "I don't know" when the sources don't contain the answer. |
| Hallucination | A fluent, confident answer that isn't supported by the sources (or by reality). |
| Streaming, SSE | Sending the answer word by word as it's generated; server-sent events is the simple web standard for that. |
| Time to first token | How long until the first word appears: what makes an answer feel fast. |
| Conversation memory | The earlier turns of a chat, kept so follow-ups make sense. |
| Exact / semantic cache | Reusing an answer for the same question (same words), or for a question with nearly the same meaning. |
| Cache invalidation, epoch | Making old cached answers unusable when documents change; here, by bumping a counter that is part of every key. |

> **IN PLAIN ENGLISH**
> The model never "knows" your company's policies. We hand it a numbered stack of the passages this person is
> allowed to read, tell it to answer only from them and to say which passage each claim came from, and then
> check its homework: any reference to a passage it wasn't given is crossed out, and an answer that cites
> nothing is flagged (or replaced with "I don't know").

### Citations, checked (Figure 105)

```
 context sent to the model                                 model's reply
   <doc id="1" title="Remote work policy">                   Up to three days a week [doc 1]; a $400
   You may work from home up to three days a week…           allowance [doc 2]; bonus 10% [doc 7].
   <doc id="2" title="Remote work policy › Home office setup">
   New remote workers receive a one-off $400…              after the citation check
   <doc id="3" title="Laptops and devices">                  Up to three days a week [doc 1]; a $400
   Laptops are replaced every three years…                   allowance [doc 2]; bonus 10%.

 [doc 7] pointed at nothing that was shown: removed and counted (invalid_citations).
 Kept markers become links: [doc 1] → remote-work.md · document id for audit · title for the reader.
 No valid citation at all? uncited: keep · flag (default) · abstain — your choice per project.
```

The model sees numbered documents and must cite them by number. After it answers, every marker is checked
against what was actually shown: the marker for document 7 pointed at nothing and is removed. Valid markers
become links with document ids and titles. What happens to an answer with no valid citation is a
per-project choice.

### Caching without leaking (Figure 106)

```
 who can see what     the question       the conversation   settings         prompt + model        index epoch
 principal            normalised words   earlier turns      rag.yaml hash    rag-answer@2, model   +1 on every
 fingerprint                                                                                       ingest/delete
                                       ↓
                           cache key = sha256(all six)

 Same key = same answer, safely: two people share a cached answer only if they can see exactly the same documents.
 Exact (memory or Valkey) needs the same words; semantic reuses answers to near-identical questions (riskier: measure).
 A Valkey cache is shared by replicas, and one epoch counter invalidates all of them when any document changes.
```

> **ANALOGY · THE PHOTOCOPIED ANSWER**
> A cached answer is a photocopy of an earlier answer. You may hand the copy to someone else only if they
> could have read every page the original was written from (same fingerprint), only for the same question
> (same words, same conversation), only if it was written under the same rules (prompt, model, settings),
> and never after any of the pages changed (new epoch). Miss any one of those and the photocopy goes in the
> bin.

## How to do it

All commands run from the repository root (`~/dev/rag-platform` on your Mac).

### 1 · Context, citations and generators

File: [`libs/rag-core/src/rag_core/components/generation.py`](../../libs/rag-core/src/rag_core/components/generation.py)

```
hits ─context_builder─▶ <doc id="1">…</doc> <doc id="2">…</doc>       (within a token budget)
     ─generator─▶ "Staff get 20 days [doc 1]."  ─citations─▶ [doc 1] → leave-policy.md
```

What the file holds:

- **`PackedContext`**: the context text, the chunks in the order shown (`[doc n]` is `chunks[n - 1]`), the
  tokens used and how many candidates didn't fit (`dropped`).
- **`neutralise()`**: turns `</doc>`, `<doc`, `</documents>` and `<question` inside a document into
  look-alikes (the `<` becomes U+2039, `‹`), so a document's text can never close its own block and pose as
  another document or as an instruction.
- **`ContextParams` / `NumberedContext`** (`context_builder: numbered`): `max_tokens` (3000: the whole
  context, leaving room for the question and answer), `max_chunk_tokens` (800: one chunk can't take
  everything), `order` (`relevance` | `lost-in-middle` | `document`), `compress` (keep only sentences that
  share words with the question) and `min_chunks` (always include at least this many, even if cut). Each
  chunk becomes `<doc id="n" title="…" section="…" page="…">text</doc>`.
- **`check_citations()`**: finds `[doc 3]`, `[3]` and `[doc 1, 2]`, keeps the numbers that point at a shown
  document, removes the rest and reports them in `invalid`; tidies the space left before punctuation.
- **`is_abstention()`**: recognises "I don't know…", "I do not know…" and the standard abstention sentence
  `I don't know based on the available documents.`
- **`GeneratorParams` / `LlmGenerator`** (`generator: llm`): `llm_slot` (`answer_llm`, falling back to
  `llm`), `prompt` (`rag-answer`: a registered, versioned prompt, or `None` for a built-in one), `prompts_dir`,
  `prompt_label`, and optional `max_tokens` / `temperature` overrides (otherwise the prompt's own params,
  else 800 and 0.2). It fills the prompt with the context and question, calls the model whole
  (`complete_with_usage` when the client has it, so token counts come back) or streamed, and records the
  model and `rag-answer@N` on every answer.
- **`ExtractiveParams` / `ExtractiveGenerator`** (`generator: extractive`): no model. It quotes the
  sentences that share the most content words with the question (stop words don't count; long questions
  need more in common; only sentences nearly as good as the best), each with its `[doc n]`, in reading
  order, and abstains when nothing matches well.
- **`AnswerParams`** (`pipeline: standard`): `search_k` (8 chunks retrieved for the builder to choose
  from), `abstain_without_hits` (true), `uncited` (`keep` | `flag` | `abstain`, default `flag`),
  `abstain_text`, `history_turns` (6). Step 35 adds other architectures to the same `pipeline` slot.

> **READING THE GENERATION COMPONENTS**
> - The id is the citation number, not a database id: short numbers are what models cite reliably. Titles,
>   sections and pages ride along as attributes so the model can say "the remote work policy says…".
> - `neutralise` turns `</doc>`, `<doc`, `</documents>` and `<question` inside a document into look-alikes,
>   so text in a document can never close its block and pose as another document or an instruction. The
>   registry adds the same protection for the question (Step 24).
> - The budget is greedy but forgiving: a chunk that doesn't fit is skipped, and a smaller one further down
>   may still fit. One very long chunk is cut at a sentence boundary rather than dropped.
> - `check_citations` accepts `[doc 3]`, `[3]` and `[doc 1, 2]`, keeps the numbers that point at a shown
>   document, removes the rest and reports them.
> - `LlmGenerator` loads the registered prompt version for this environment's label, so the prompt text,
>   model, temperature and token limit all come from a reviewed, locked file, and every answer records
>   `rag-answer@N`.
> - `ExtractiveGenerator` has no model: it quotes the sentences that best match the question, each with its
>   citation, and abstains when nothing matches well. It's the offline default and a dependable fallback; it
>   can't paraphrase, combine or reason.
> - `AnswerParams` is the pipeline slot: Step 35 adds other architectures to the same slot.

### 2 · Memory and caches

File: [`libs/rag-core/src/rag_core/components/conversation.py`](../../libs/rag-core/src/rag_core/components/conversation.py)

- **`session_key()`** = `tenant:subject:session_id`. The person is part of the key: knowing someone's session
  id doesn't give you their history.
- **Memory** (`memory` slot): `memory` (in this process; lost on restart, not shared between replicas) and
  `valkey` (shared by every replica, expiring on its own; the key is a SHA-256 of the session key under
  `rag:memory:`). Both keep at most `max_turns` (10) turns and forget a conversation after `ttl_seconds`
  (86 400, a day) of silence. Valkey's URL comes from `url_file` (`/run/bao/valkey_url`, rendered by
  OpenBao Agent) or the `url_env` variable (`RAG_VALKEY_URL`).
- **`cache_key()`**: SHA-256 of the principal's fingerprint, the normalised question (lower-case words),
  the conversation so far and a version string (settings hash, prompt version, model, index epoch).
- **Caches** (`cache` slot):
  - `memory`: exact match in this process, LRU (`max_items`, 10 000) + TTL (`ttl_seconds`, 3600);
    `invalidate()` starts a new epoch and empties it.
  - `valkey`: exact match in Valkey (`rag:answer:` prefix), shared by replicas; the epoch is a counter in
    Valkey, so one ingestion change invalidates every replica at once, and old keys simply expire.
  - `semantic`: reuses an answer for a question that means nearly the same (embedding cosine similarity ≥
    `threshold`, 0.95 by default), only for the same access fingerprint and the same epoch, at most
    `max_items` (2000) rows; an exact hit is tried first.

> **READING MEMORY AND CACHES**
> - A session belongs to a person: the key includes tenant and subject, so guessing someone's session id gets
>   you nothing.
> - Memory forgets: turns are capped (`max_turns`) and expire (`ttl_seconds`, a day by default). Questions are
>   personal data; keep the TTL as short as the product allows and say so in the privacy notice.
> - The exact cache key is a hash of the access fingerprint, the normalised question, the conversation and a
>   version string (settings hash, prompt version, model, index epoch). Nothing else can make two answers
>   equal.
> - Invalidation by epoch: `invalidate()` bumps a counter that is part of every key. In Valkey the counter is
>   shared, so one ingestion change invalidates every replica at once; old entries simply expire.
> - The semantic cache is deliberately opt-in, threshold 0.95, same access set only, and never for
>   follow-ups.

> **WATCH OUT**
> The semantic cache is the risky one. "How much leave do primary carers get?" and "How much leave do
> secondary carers get?" can look 96% alike to an embedding model, and have different answers. Measure false
> hits on real questions before switching it on, and keep it off for regulated advice.

### 3 · The pipeline

File: [`libs/rag-core/src/rag_core/answer.py`](../../libs/rag-core/src/rag_core/answer.py)

```python
pipeline = AnswerPipeline(config.load("rag.yaml", "local"))
answer = pipeline.answer("How many leave days do I get?", principal, session_id="s-42")
for event in pipeline.stream(...): ...   # ("meta", …), ("delta", "Full"), …, ("done", Answer)
```

Order of work, and why:

| Stage | Why here |
|---|---|
| memory | the conversation so far, so follow-ups make sense |
| guards (input) | input checks (Step 34) before anything is spent |
| cache | same question, same access, same index and prompt: reuse |
| search | Step 32's pipeline (+ the caller's own post-check, e.g. OPA in rag-api) |
| abstain | nothing relevant found: say so, without calling a model |
| context | numbered `<doc>` blocks within a token budget |
| generate | the registered prompt, the answer model; streamed or whole |
| cite | keep only citations that point at a document that was shown |
| guards (output) | output checks (Step 34) |
| remember, cache, return | with a trace of everything above |

`AnswerPipeline` takes everything from the container: `pipeline` (or `AnswerParams()` defaults),
`context_builder` (or a numbered one with the profile's token counter), `generator`, and the optional
`memory`, `cache` and `guards`. `answer()` returns an `Answer` (text, citations, `abstained`, `blocked`,
`usage`, and a `trace` with flags, cache hit/miss, the search trace, the post-check's drop count, the
context's chunk ids and tokens, the model, the prompt, invalid citations, `uncited`, and milliseconds).
`stream()` yields one `meta` event (which documents the answer is based on), `delta` events and one `done`
event with the checked answer. `answer_dict()` turns an answer into plain JSON.

> **READING THE PIPELINE**
> - `post_check` is how a service adds its own authorisation: rag-api passes a function that asks OPA about
>   every document before the context is built.
> - `before_generation` is how a service records the audit event at exactly the right moment: after it's known
>   which documents the model will see, before any text exists.
> - Guards (Step 34) run at three stages: input (the question), context (the chunks), output (the answer). A
>   guard can block, redact (replace the payload) or flag. The hook is here and tested now with fake guards;
>   Step 34 adds the real ones.
> - Abstaining early is cheap: no hits means no context and no model call.
> - Streaming yields one meta event (which documents the answer is based on), delta events with text, and one
>   done event with the checked answer, so a client can show sources before the first word and replace the
>   streamed text with the checked text at the end.

The LLM client gains token counts and streaming, in
[`libs/rag-core/src/rag_core/components/basics.py`](../../libs/rag-core/src/rag_core/components/basics.py):

- `GatewayLLM.complete_with_usage()` returns the reply and the token counts the gateway reported (for budgets,
  audit and cost).
- `GatewayLLM.stream()` posts with `"stream": true` and `"stream_options": {"include_usage": true}`, reads the
  `data:` lines until `[DONE]`, yields each content delta and, if given a `usage` dict, fills it from the final
  event. No retries once text has been sent.
- `ScriptedLLM` (the offline test model) gains both too, counting words as stand-in tokens and streaming word
  by word.

Ingestion now ends a cache epoch, and a new `answer_llm` slot lets the answer model differ from the helper
model:

- [`ingest.py`](../../libs/rag-core/src/rag_core/ingest.py): the pipeline takes the profile's `cache` and
  calls `invalidate()` after every delete and every successful (`indexed`) ingest, so no cached answer
  outlives the documents it was based on (a Valkey cache does this for every replica at once).
- [`registry.py`](../../libs/rag-core/src/rag_core/registry.py): `answer_llm` is a slot of kind `llm`.

### 4 · Profiles

File: [`rag.yaml`](../../rag.yaml) (the new and changed lines)

```yaml
  offline:
    query_transformer: with-history   # identity | expand-terms | with-history | rewrite | …
    postprocessors:
      - {use: dedupe, threshold: 0.85}
      - {use: recency, weight: 0.15, half_life_days: 730}   # needs an "updated" date in metadata
      - {use: max-per-document, n: 3}
    # answers (Step 33)
    pipeline: {use: standard, search_k: 8, uncited: flag}
    context_builder: {use: numbered, max_tokens: 3000, order: relevance}   # relevance | lost-in-middle | document
    generator: {use: extractive, max_sentences: 3}   # no model offline; "llm" uses the registered prompt
    memory: {use: memory, max_turns: 10}
    cache: {use: memory, ttl_seconds: 3600}          # memory | valkey | semantic

  local:
    extends: offline
    answer_llm: {use: gateway, model: qwen-quality, base_url: "http://litellm:4000/v1", api_key_file: /run/bao/rag_api_gateway_key}
    generator: {use: llm, llm_slot: answer_llm, prompt: rag-answer, prompts_dir: /app/prompts, prompt_label: production}
    memory: {use: valkey, url_file: /run/bao/valkey_url, ttl_seconds: 86400}
    cache: {use: valkey, url_file: /run/bao/valkey_url, ttl_seconds: 3600}
    query_transformer: {use: rewrite, llm_slot: llm}   # follow-ups made standalone (no call without history)
    postprocessors:
      - {use: dedupe, threshold: 0.85}
      - {use: min-score, stage: rerank, threshold: 0.05, min_keep: 1}
      - {use: recency, weight: 0.15, half_life_days: 730}
      - {use: max-per-document, n: 3}
```

> **READING THE PROFILES**
> - `offline` answers with the extractive generator, in-process memory and cache, and Step 32's free
>   `with-history` follow-ups. Runs anywhere.
> - `local` uses `qwen-quality` as the answer model (`answer_llm`), `qwen-fast` for helpers (`llm`: query
>   rewriting only when there is a conversation), the registered `rag-answer` prompt at this environment's
>   label, and Valkey for memory and cache, so every replica shares them.
> - The `production` label still points at `rag-answer@1`, which doesn't ask for citations, so answers are
>   flagged as uncited. Promote `rag-answer@2` only after Step 26's evaluation passes on your model:
>   `just prompts promote rag-answer 2 production` (a pull request, as always).

To match the comment "no call without history", the `rewrite` query transformer
([`retrieval.py`](../../libs/rag-core/src/rag_core/components/retrieval.py)) now returns the question
unchanged, without a model call, when there is no conversation yet.

### 5 · Try it

A conversation (later questions can be follow-ups):

```bash
uv run rag ask "How many days a week can I work from home?" \
  "How much parental leave do primary carers get?" "Can I take it in two blocks?" \
  "How big is the executive bonus pool?" \
  --profile offline --group all-staff --corpus examples/eval/handbook.yaml
```

Output on this repository's sample handbook:

```text
Q: How many days a week can I work from home?
A: Staff may work from home up to three days a week, agreed with their manager [doc 1].
     [doc 1] remote-work.md                 (Remote work)
     abstained=False cache=miss model=extractive prompt=none context=8 chunks ms=10.7

Q: How much parental leave do primary carers get?
A: Parental leave can be taken in one continuous period or split into up to two blocks, as long as all of it is taken within 24 months of the birth or placement [doc 2]. You may work up to 10 paid keeping-in-touch days during parental leave without ending it [doc 2]. The primary carer of a new child, by birth, adoption or permanent care, receives 18 weeks of parental leave at full pay, plus superannuation on the unpaid portion of any extended leave [doc 3].
     [doc 2] parental-leave.md              (Parental leave policy)
     [doc 3] parental-leave.md              (Parental leave policy)
     abstained=False cache=miss model=extractive prompt=none context=8 chunks ms=22.1

Q: Can I take it in two blocks?
A: Parental leave can be taken in one continuous period or split into up to two blocks, as long as all of it is taken within 24 months of the birth or placement [doc 2].
     [doc 2] parental-leave.md              (Parental leave policy)
     abstained=False cache=miss model=extractive prompt=none context=8 chunks ms=8.0

Q: How big is the executive bonus pool?
A: I don't know based on the available documents.
     abstained=True cache=miss model=extractive prompt=none context=8 chunks ms=9.2
```

> **READING THE OUTPUT**
> - "Can I take it in two blocks?" worked because memory supplied the previous question and `with-history`
>   searched with both.
> - The executive bonus exists in the corpus, but only for the `executives` group: this person's search never
>   sees it, so the answer is an abstention, not a leak.
> - `--corpus` ingests the evaluation file's documents with their real access rules (the restricted document
>   stays restricted).

The cache (separate questions, same access):

```bash
uv run rag ask "How many days a week can I work from home?" "how many days a week can I work from home" \
  --no-memory --profile offline --group all-staff --corpus examples/eval/handbook.yaml
```

```text
Q: How many days a week can I work from home?
A: Staff may work from home up to three days a week, agreed with their manager [doc 1].
     abstained=False cache=miss model=extractive prompt=none context=8 chunks ms=10.3

Q: how many days a week can I work from home
A: Staff may work from home up to three days a week, agreed with their manager [doc 1].
     abstained=False cache=hit model=extractive prompt=none context=8 chunks ms=0.2
```

Streaming:

```bash
uv run rag ask "What does VPN error E-1107 mean?" --stream \
  --profile offline --group all-staff --corpus examples/eval/handbook.yaml
```

```text
Q: What does VPN error E-1107 mean?
A: E-1107 means the MFA push timed out [doc 1].
     [doc 1] vpn-troubleshooting.md         (VPN troubleshooting)
     abstained=False cache=miss model=extractive prompt=none context=8 chunks ms=-
```

`--json` prints each answer as JSON instead (text, citations, usage, cache, model, prompt). If the citation
check changed a streamed draft, `--stream` prints the checked text underneath.

`uv run rag components` now lists the new kinds: `context_builder numbered`; `generator extractive` and
`llm`; `memory memory` and `valkey`; `cache memory`, `semantic` and `valkey`; `pipeline standard`, each with
its parameters and defaults.

### 6 · rag-api: `/v1/answer` and `/v1/feedback`

File: [`services/rag-api/src/rag_api/main.py`](../../services/rag-api/src/rag_api/main.py)

Shared components: `get_core()` loads rag-core's container (rag.yaml + profile) once, shared by search and
answers; `get_search()` builds `CoreSearch` on it; `get_answerer()` builds an `AnswerPipeline` on it;
`get_tenant()` returns this deployment's tenant.

The endpoints:

- **`AnswerRequest`**: `question` (1–2000 characters), `session_id` (optional, up to 64 of `A-Z a-z 0-9 _ -`:
  a conversation is remembered per person AND session), `stream` (false).
- **`AnswerOut`**: `answer_id` (send it back with `/v1/feedback`; it is also the trace id, Steps 19–23),
  `text`, `abstained`, `blocked`, `citations` (each `n`, `document_id`, `title`).
- **`POST /v1/answer`**: `authorize("answer")` asks OPA; OPA's filter (groups and classifications) becomes
  the rag-core principal; `post_check` asks OPA about every document before it can reach the model (and
  counts and logs mismatches, as `/v1/search` does); `record` writes the audit event before anything is handed
  out. For JSON answers the event is written after generation and before the response; for streams,
  `next(events)` runs search, the OPA post-check and the audit write before the response starts. The
  stream sends `event: meta` (with the answer id and the documents), `event: delta` frames, and a final
  `event: done` with the checked answer; a model failure mid-stream sends `event: error`, never a `done`.
  Response headers: `Cache-Control: no-store`, `X-Accel-Buffering: no` (so proxies don't buffer the stream).
- **`POST /v1/feedback`**: `answer_id` (32 hex characters), `rating` (`up` | `down`), `reason` from a fixed
  list (`wrong`, `incomplete`, `outdated`, `not_relevant`, `unsafe`, `other`); recorded in the audit log as
  `feedback` on `answer:<id>`; returns 202.
- New metrics: `rag.answer.requests` (by outcome: answered, abstained, blocked, error),
  `rag.answer.duration` (whole answers, or until the stream starts: time to first token) and
  `rag.answer.feedback` (by rating and reason).

> **READING THE ENDPOINTS**
> - Same front door as search: token check, `authorize("answer")` asks OPA, the OPA filter becomes the
>   rag-core principal, OPA re-checks every document before the model sees it.
> - Fail closed on audit: for JSON answers, the event is written after generation and before the response;
>   for streams, `next(events)` runs search, the OPA post-check and the audit write before the response
>   starts, so a failure is a real `503`, never a half-sent answer. A model failure mid-stream sends an error
>   event, never a `done`.
> - What the audit event holds: answer id, the document ids given to the model, the ids cited, the outcome,
>   cache hit or miss, prompt version, model, token counts, question length, whether it was a conversation.
>   Never the question or answer text (Step 23).
> - `answer_id` is the trace id, so feedback, the audit event, Tempo and Langfuse traces all join on one value.
> - Feedback reasons are a fixed list: free text would collect names and complaints into a log that is kept
>   for years.

Policy: [`policies/rag/authz/data.json`](../../policies/rag/authz/data.json) gains `"answer": "rag-user"` and
`"feedback": "rag-user"` in `action_roles`, and
[`authz_test.rego`](../../policies/rag/authz/authz_test.rego) three tests: a user may answer and rate, the
ingestion worker (a machine without `rag-user`) may not answer, and an answer uses exactly the search filter.

Network: [`deploy/base/rag-api/networkpolicy.yaml`](../../deploy/base/rag-api/networkpolicy.yaml) lets rag-api
out to port 6379 (Valkey: conversation memory and the answer cache). In Compose, rag-api now also waits for a
healthy `valkey`.

Step 17's demo script [`scripts/api_demo.py`](../../scripts/api_demo.py) gains the new calls after the admin
call: an answer, a follow-up in the same session, a streamed answer, and feedback on the first answer.

```bash
just api-up && just api-demo      # sign in as alice when asked
```

> **NOT RUN IN THIS GUIDE'S ENVIRONMENT**
> The demo needs the platform from Steps 7–29 (models, LiteLLM, Valkey, Keycloak, OPA) on your Mac.
> Everything it calls is covered by the tests below with the real FastAPI app, fake identity and policy
> services, and the real rag-core pipeline.

### 7 · Test it

Files: [`libs/rag-core/tests/test_answer.py`](../../libs/rag-core/tests/test_answer.py) (20 tests) and
[`services/rag-api/tests/test_answer_api.py`](../../services/rag-api/tests/test_answer_api.py) (8 tests).

```bash
just audit-test       # everything, with the throwaway Postgres
just policy-check     # 27 policy tests
uv run pytest libs/rag-core/tests/test_answer.py services/rag-api/tests/test_answer_api.py   # 28 passed
```

> **WHAT THE TESTS PROVE**
> - Context: numbering, budget, per-chunk cuts, the three orders, compression, and that a document can't
>   forge `</doc><doc id="9">`.
> - Citations: valid markers kept, invalid removed and reported, mixed markers fixed; abstentions recognised.
> - Generators: the registered prompt `rag-answer@2` is used with its system message and boxed question;
>   token counts come back; the gateway's server-sent events stream with usage; the extractive generator
>   quotes with citations or abstains.
> - Pipeline: right citation, restricted document invisible, no model call when nothing is found, all three
>   uncited policies, the post-check, follow-ups through memory, sessions isolated per person, cache hits only
>   within an access set and gone after ingestion, the semantic cache's limits, Valkey memory trimming and
>   TTLs and epoch invalidation, streaming order, and guards that block, redact and flag.
> - rag-api: citations with document ids and an audit event without any text, follow-ups by session, OPA's
>   post-check reaching the model, no audit means no answer (JSON and stream), 403 and 503 from the policy,
>   the event stream's shape and its audit-first order, and feedback validation.

### 8 · Record the decision

[`docs/adr/0033-answer-with-checked-citations-and-abstention.md`](../adr/0033-answer-with-checked-citations-and-abstention.md):
answer from numbered sources, check citations, abstain rather than guess. Alternatives rejected: trusting the
model's citations (it cites documents it never saw), always calling the model (pays to invent an answer),
caches keyed by question only (leaks across permission sets), a semantic cache by default (near-identical
questions with different answers), WebSockets (harder through proxies), and storing questions and answers
in the audit log (personal data in a long-lived log).

## Benefits

- Trustworthy by construction: permitted sources only, checked citations, honest abstentions.
- Fast where it matters: streaming for the first words, caches for repeats, no model call when there's
  nothing to say.
- Safe to cache: answers are shared only between people with identical access, and never outlive a document
  change.
- Conversations that work, isolated per person, forgotten on schedule.
- Accountable: the audit event comes first; feedback ties back to the exact answer.
- Switchable: context builder, generator, memory, cache and prompt version are configuration.

## Drawbacks and risks

- Citations are only as good as the model's discipline. A model can cite the right document for a wrong
  claim; Step 34's groundedness check and Step 26/37 evaluation measure that.
- Abstaining too often (strict thresholds, `uncited: abstain`) frustrates users; too rarely invites
  invention. Tune with real questions.
- Streaming complicates checks: text is sent before citations and output guards finish. The `done` event
  carries the checked text; clients must replace the streamed draft, and Step 34 shows when to switch
  streaming off.
- Memory is personal data, and caches hold answers derived from documents; both need retention rules and
  must be cleared on erasure requests (Step 36).
- Extractive answers are stilted and can quote an outdated sentence if retrieval ranks it; it's a fallback,
  not a product.

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| Numbered `<doc>` context + checked citations (default) | What this step builds | Most question-answering |
| Quote-then-answer | The model first copies supporting quotes, then answers from them | High-stakes answers that must be verifiable sentence by sentence |
| Native citation APIs (Anthropic citations, Cohere documents mode) | The model returns spans of the sources | You use those providers through the gateway |
| Refine / map-reduce | Answer per chunk, then combine | Very long sources that don't fit one context |
| LLMLingua / LongLLMLingua compression | A small model removes low-value tokens | Context budget is the bottleneck |
| Long-term memory stores (mem0, Zep, LangGraph memory) | Facts about the user kept across sessions | Personal assistants, with consent |
| GPTCache / Redis semantic cache | Ready-made semantic caching | Very high repeat traffic; measure false hits |
| WebSockets | Two-way streaming | Interactive agents that need to send mid-answer |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Employee Q&A over policies | Defaults + `rag-answer@2` + `uncited: flag` |
| Regulated advice (finance, health, legal) | `uncited: abstain`, quote-then-answer, Step 34's groundedness guard, no semantic cache, streaming off |
| Chat assistant | Valkey memory, rewrite follow-ups, streaming on |
| High-volume repeated questions (IT help desk) | Valkey exact cache; semantic cache only after measuring false hits |
| Offline, demo, model outage | Extractive generator |
| Long documents, small model | Compression or parent-expand with a tighter budget; lost-in-middle ordering |

## Common mistakes

- Letting the model see documents the user can't "because it will only summarise".
- Trusting model citations without checking them against the context.
- Calling the model when retrieval found nothing.
- Caching by question only, across users with different access.
- Never invalidating the cache when documents change.
- Logging questions and answers in the audit log or application logs.
- Streaming without a final checked answer, so unchecked text is all the user ever gets.
- Session ids without the user in the key.

## Done when

- [ ] `uv run rag ask … --corpus examples/eval/handbook.yaml` answers with citations, handles the follow-up
      and abstains on the executive question
- [ ] The second, identical question shows `cache=hit`; `--stream` streams
- [ ] `just policy-check` passes with the `answer` and `feedback` actions
- [ ] With the platform up: `/v1/answer` answers with citations and streams; `/v1/feedback` returns 202; the
      audit log shows `answer` and `feedback` events with ids only
- [ ] You decided when `rag-answer@2` goes to production (after Step 26's evaluation on your model)
- [ ] `just audit-test` passes
- [ ] ADR-0033 is committed

## Recap

> **RECAP**
> The platform now answers, and can show its working:
> - context packed within a budget, numbered, impossible for documents to forge
> - citations checked against what was shown; uncited answers flagged; abstention when nothing fits
> - conversations remembered per person and session; caches shared only within an access set and reset by
>   any document change
> - `/v1/answer` (JSON or live stream) and `/v1/feedback`, with OPA and an audit record that always comes
>   first
>
> Next, Step 34: guardrails, the checks that run before and after the model: prompt injection, personal data,
> topics, toxicity, groundedness and more.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `libs/rag-core/src/rag_core/components/generation.py` | Numbered context builder, `neutralise`, citation checking, abstention detection, the `llm` and `extractive` generators, the `standard` pipeline settings |
| `libs/rag-core/src/rag_core/components/conversation.py` | Conversation memory (process, Valkey) and answer caches (memory, Valkey, semantic) with epoch invalidation; `cache_key` |
| `libs/rag-core/src/rag_core/answer.py` | `AnswerPipeline` (answer and stream), the guard hook, `Event`, `answer_dict` |
| `libs/rag-core/src/rag_core/components/basics.py` (changed) | `GatewayLLM.complete_with_usage` and `stream` (SSE with usage); the same on `ScriptedLLM` |
| `libs/rag-core/src/rag_core/components/retrieval.py` (changed) | `rewrite` makes no model call when there is no conversation |
| `libs/rag-core/src/rag_core/registry.py` (changed) | The `answer_llm` slot |
| `libs/rag-core/src/rag_core/ingest.py` (changed) | Every ingest and delete starts a new cache epoch |
| `libs/rag-core/src/rag_core/evaluate.py` (changed) | `ingest_corpus` is public, shared by eval-search, `rag ask --corpus` and the tests |
| `libs/rag-core/src/rag_core/cli.py` (changed) | `rag ask` (follow-ups, `--stream`, `--no-memory`, `--json`, `--corpus`) |
| `libs/rag-core/tests/test_answer.py` | 20 tests: context, citations, generators, pipeline, memory, caches, streaming, guards, CLI |
| `rag.yaml` (changed) | Answer slots in `offline`; answer model, registered prompt, Valkey memory and cache, rewrite in `local`; recency in both |
| `services/rag-api/src/rag_api/main.py` (changed) | `get_core`, `get_answerer`, `get_tenant`; `/v1/answer` (JSON or SSE, audit first) and `/v1/feedback`; answer metrics |
| `services/rag-api/src/rag_api/search.py` (changed) | `document_id()` is public (used by answers too) |
| `services/rag-api/tests/test_answer_api.py` | 8 tests: citations and audit, follow-ups, OPA post-check, no audit no answer, policy 403/503, the event stream, feedback |
| `services/rag-api/tests/test_service.py` (changed) | The OpenAPI listing includes the two new endpoints |
| `policies/rag/authz/data.json`, `policies/rag/authz/authz_test.rego` (changed) | `answer` and `feedback` actions for `rag-user`, three new policy tests |
| `deploy/base/rag-api/networkpolicy.yaml` (changed) | Egress to Valkey (6379) |
| `infra/compose/compose.yaml`, `tests/test_rag_api.py` (changed) | rag-api waits for a healthy Valkey |
| `scripts/api_demo.py` (changed) | Answer, follow-up, stream and feedback calls |
| `docs/adr/0033-answer-with-checked-citations-and-abstention.md` | ADR-0033 |
| `docs/glossary.md`, `docs/adr/README.md`, `docs/steps/README.md`, `CHANGELOG.md` (changed) | New terms, indexes, changelog |

## Notes for this repository

- **Code reconstructed from the PDF.** The listings were extracted from the PDF and their indentation and
  line wraps rebuilt; `ruff format` re-wrapped a few long lines. Small additions that don't change the
  design: when `LlmGenerator.stream` falls back to a whole answer it still fills `usage`; answer caches
  serialise traces with `default=str`; `rag-api`'s stream counts an error if the first step (search, policy,
  audit) fails, and its post-check fails closed when OPA grants no classification (as `CoreSearch` does);
  rag-api builds the rag-core principal with a `cast` instead of a `type: ignore`.
- **`rag ask` was written for this repository.** The guide shows its use and output but not its code; it was
  added to the existing CLI to produce exactly that output (`--corpus`, `--stream`, `--no-memory`, `--json`).
  `evaluate._ingest` was renamed `ingest_corpus`, the name the guide's tests use.
- **`ScriptedLLM` gained `complete_with_usage` and `stream`.** The guide's generator test expects token counts
  from the offline model (`completion_tokens == 4` for "Twenty days [doc 1]."); words stand in for tokens.
- **`rewrite` without history.** The guide's `rag.yaml` says the rewrite transformer makes "no call without
  history"; Step 32's transformer still called the model, so it now returns the question unchanged when there
  is no conversation.
- **The sample handbook differs from the guide's.** This repository's handbook was written in Step 32, so the
  outputs above differ in wording from the guide's (for example "Staff may work from home…", title "Remote
  work"), and two test expectations were adapted: the executive bonus figure is "4.2 million" (the guide's
  is "2.4 million") and the remote-work document's title is "Remote work" (the guide's is "Remote work
  policy"). The behaviour tested is the same.
- **Test layout.** rag-api's tests aren't a package (pytest runs with `--import-mode=importlib`), so the
  answer API tests import the conftest types under `TYPE_CHECKING` and define `bearer` locally, as Step 32's
  `test_core_search.py` does, instead of the guide's `from .conftest import …`.
- **Compose waits for Valkey.** The guide only opens the Kubernetes network policy; because the `local`
  profile now needs Valkey for memory and cache, rag-api's Compose service also depends on a healthy `valkey`
  (the `valkey_url` file is already rendered by rag-api's OpenBao agent since Step 31).
- **What was validated here.** ruff, ruff format, strict mypy and the full pytest suite (628 passed, the live
  service tests skipped); `opa fmt`, `opa check --strict` and `opa test` with coverage ≥ 90 % (27/27 passed,
  using a downloaded OPA 1.21 binary; `regal` was not available); `rag config validate` for all three
  profiles; `just search-eval` (still recall 1.0, MRR 1.0 with the new offline defaults); the `rag ask`
  commands above. The platform demo needs models, LiteLLM, Valkey, Keycloak and OPA and was not run here.
