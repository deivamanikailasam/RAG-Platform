# Step 7 · Serving both Qwen models with mlx-lm

*Step 7 of 38 · Phase B · Model serving*

## At a glance

| | |
|---|---|
| **Goal** | Run your two local models as always-on, OpenAI-compatible HTTP servers on your Mac, then measure their real speed and memory, replacing Step 3's estimates. **Qwen3.8-27B-8bit on port 8081** is the careful, high-quality writer; **Qwen3.6-35B-A3B-4bit on port 8082** is the fast helper. |
| **Time** | About 90 minutes, plus download time (~50 GB of model files). |
| **You'll end up with** | An isolated, version-locked `infra/model-serving` project; pinned model revisions recorded in a model inventory; two servers kept alive by macOS launchd; a benchmark script, a results table, and ADR-0007. |
| **New words** | Token, tokenizer, prefill, decode, TTFT, tokens per second, KV cache, context window, quantization, Mixture of Experts, active parameters, chat template, thinking mode, OpenAI-compatible API, endpoint, CORS, launchd, model revision, wired memory, memory bandwidth, speculative decoding. |

## The big idea

> **ANALOGY · TWO SPECIALIST WRITERS ON CALL**
> You're hiring two writers who work from your office (your Mac's GPU):
>
> - **The careful senior writer** (27B, 8-bit) is thoughtful and precise, but slower.
> - **The quick assistant** (35B-A3B, 4-bit) has a huge library in their head, but only consults a small part of it
>   for each word, so they answer fast. Use them for quick jobs: rewriting a question, deciding which tool to use,
>   short replies.
>
> Each writer sits at their own desk with a numbered phone line (port 8081, port 8082). Anyone in the office can
> call them in a standard way (the OpenAI-compatible API). In Step 9 a receptionist (LiteLLM) will take every call
> first, checking who's calling and keeping a log.

## What we're doing

1. Create an isolated serving project (`infra/model-serving`) with mlx-lm at a locked version.
2. Download both models from Hugging Face, record their exact revisions in a model inventory, then serve
   offline.
3. Check the GPU memory limit macOS allows, and learn when (and when not) to raise it.
4. Run each model as an OpenAI-compatible server on localhost, with safe settings.
5. Talk to them with `curl`, including the thinking-mode switch.
6. Benchmark time-to-first-token, tokens per second and peak memory, and record the results.
7. Keep both servers running with launchd (start at login, restart on crash).
8. Add `just` recipes and ADR-0007.

## Why we're doing this

> **WHY THIS MATTERS**
> Every later project calls these models: to rewrite questions, write answers, judge quality, and extract entities.
> If serving is unreliable, slow or unmeasured, every RAG experiment is unreliable too. Measuring now gives you the
> baseline numbers that latency budgets, capacity planning and model-choice decisions will be built on.

| Need | How this step meets it |
|---|---|
| Two models with different strengths, used for different jobs | Separate servers on 8081 (quality) and 8082 (speed) |
| Reproducibility: the "same model" must really be the same | Locked mlx-lm version, pinned model revisions, offline serving |
| One standard way for every service to call a model | OpenAI-compatible API (`/v1/chat/completions`), used by LiteLLM, LangChain, LlamaIndex, DSPy and the OpenAI SDK |
| Real numbers instead of guesses | A benchmark of TTFT, tokens/s and peak memory, written down |
| Always available, without babysitting terminals | launchd services with automatic restart and log files |
| Safety on a laptop | Bound to 127.0.0.1, restricted CORS, and (in Step 9) reached only through the gateway |

> **IN A COMPANY**
> This is the **model serving layer**. In production it runs on GPU servers using engines like vLLM, TGI or
> TensorRT-LLM, sits behind a gateway, and is measured with exactly the metrics you'll collect here: TTFT, tokens per
> second, throughput under concurrency, and memory headroom. Enterprises also keep a **model inventory** (which
> model, which exact version, which licence, who approved it), which this step starts.

## Key ideas

### How a model produces an answer

A model answers in two phases:

1. **Prefill.** It reads *all* of your prompt's tokens at once (say a ~2,000-token "Explain RAG…" prompt) in one
   big parallel pass. This is limited by **compute** (the GPU cores), and it decides how long you wait before the
   first word appears: the **TTFT**.
2. **Decode.** It then writes the answer **one token at a time**, each depending on everything before it. This is
   limited by **memory bandwidth**, and it decides how fast the answer streams: the **tokens per second**.

Throughout, the **KV cache** is the model's working memory. It stores what the model has read so far and grows with
every token of prompt *and* answer, so long documents and long chats use far more memory.

*(Guide Figure 22: prefill reads the whole prompt at once and decides how long you wait for the first word; decode
writes one token at a time and decides how fast the answer streams; the KV cache grows as it goes.)*

| Term | Plain-English meaning |
|---|---|
| Token | The unit a model reads and writes: roughly ¾ of an English word. "Retrieval-augmented" might be 4 tokens. |
| Tokenizer | The model's dictionary for converting text to tokens and back. |
| Context window | The maximum number of tokens (prompt + answer) a model can handle at once. |
| Prefill | The first phase: the model reads every token of your prompt in one big parallel pass. |
| Decode | The second phase: the model writes the answer one token at a time, each depending on all before it. |
| TTFT (time to first token) | How long you wait before the first word appears. Mostly set by prefill and prompt length. |
| Tokens per second (tok/s) | How fast the answer streams once it starts. Mostly set by memory bandwidth. |
| Memory bandwidth | How fast data moves between memory and the GPU. Each decoded token reads the model's weights, so bandwidth is the speed limit. |
| KV cache | The model's working memory of everything read so far. Grows with context length and is a big part of memory use. |
| Prompt cache | Reusing the KV cache of a prompt start you've sent before (e.g. the same system prompt), which makes TTFT much faster. |

### Why these two models behave so differently

**Quantization** changes how many bytes each of the model's numbers takes. For the same 27B model (weights only):

| Number format | Approximate size | Notes |
|---|---|---|
| bf16 (16-bit) | ~54 GB | 2 bytes per number |
| 8-bit | ~27 GB | 1 byte; about the best quality/size balance |
| 4-bit | ~13.5 GB | ½ byte; smaller and faster, small quality loss |

**Mixture of Experts (MoE)**: Qwen3.6-35B-A3B stores 35B parameters (so it needs memory like a big model) but only
uses about 3B of them per token (so it runs at the speed of a small model). The "A3B" in the name means "about 3B
**active parameters**".

*(Guide Figure 23: quantization shrinks a model by storing each number in fewer bits; Mixture of Experts stores many
specialist sub-networks but only uses a few per token.)*

| | Qwen3.8-27B-8bit (quality) | Qwen3.6-35B-A3B-4bit (fast) |
|---|---|---|
| Design | Dense: all 27B parameters work on every token | Mixture of Experts (MoE): 35B stored, about 3B active per token (the "A3B") |
| Precision | 8-bit (about 1 byte per parameter) | 4-bit (about half a byte per parameter) |
| Download size (per the model pages) | ~29.5 GB | ~20.4 GB |
| Speed | Slower: reads all weights for every token | Much faster: reads only the active experts |
| Best for | Final answers, synthesis, careful reasoning, judging | Query rewriting, routing, classification, short replies, high volume |

> **IN PLAIN ENGLISH · QUANTIZATION**
> A model is billions of numbers. Quantization stores each number with fewer digits: 8-bit instead of 16-bit halves
> the size, and 4-bit quarters it. Less to read per token means faster and smaller, at the cost of a little accuracy.
> 8-bit is usually almost indistinguishable from the original; 4-bit is a good trade for speed-critical helper jobs.

### Thinking mode

Recent Qwen models can "think out loud" before answering: a hidden reasoning section, then the final answer. That
improves hard reasoning, but costs time and tokens. The mlx-lm server can switch it on or off **by default for the
whole server** (`--chat-template-args '{"enable_thinking": false}'`) and **per request**
(`"chat_template_kwargs": {"enable_thinking": false}`), if the model's chat template supports it. When thinking is
on, the server may return the reasoning in a separate `reasoning` field.

| Term | Plain-English meaning |
|---|---|
| Chat template | The model-specific recipe that turns a list of messages into the exact text format the model was trained on. |
| OpenAI-compatible API | The same request and response format as OpenAI's API, so any tool that speaks "OpenAI" can call your local model. |
| Endpoint | A specific URL path on a server, e.g. `/v1/chat/completions` or `/health`. |
| CORS | Browser rules for which websites may call a server from inside a web page. Too open, and any site you visit could call your local model. |
| launchd | macOS's built-in service manager: starts programs at login and restarts them if they crash. |
| Model revision | The exact git commit of a model repository on Hugging Face. Repositories can be updated, so "the same name" isn't always "the same model". |
| Wired memory / GPU working-set limit | The share of unified memory macOS lets the GPU lock for itself. Large models need it to be big enough. |

The chapter's word list also mentions **speculative decoding**: a small "draft" model guesses a few tokens ahead and
the big model checks them in one pass, which can speed up decoding. mlx-lm exposes it as `--draft-model`; this step
doesn't use it, but you'll see the flag in `--help`.

## How to do it

All commands run on the Mac, from the repository root (`~/dev/rag-platform`).

```bash
cd ~/dev/rag-platform
git switch -c feat/model-serving
df -h ~                      # need ~60 GB free for both models plus headroom
```

### 1 · Create the isolated serving project

The model servers run natively on macOS (ADR-0004) and depend on Apple-only MLX libraries, so they get their own
small uv project, **outside the workspace**. Its lockfile pins mlx-lm exactly, and the Linux services and CI never
install MLX by accident.

```bash
mkdir -p infra/model-serving
cd infra/model-serving
uv init --bare --python 3.12 --name model-serving     # just a pyproject.toml, no sample code
uv add mlx-lm "huggingface_hub[cli]"
uv run mlx_lm.server --help | head -40                  # see every server option for YOUR version
uv run python -c "import mlx_lm, mlx.core as mx; print('mlx-lm', mlx_lm.__version__); print(mx.default_device())"
cd ../..
```

The result is committed as [`infra/model-serving/pyproject.toml`](../../infra/model-serving/pyproject.toml) and
[`infra/model-serving/uv.lock`](../../infra/model-serving/uv.lock) (mlx-lm 0.32.0, huggingface-hub 2.2.0 at the time
of writing). The root `pyproject.toml` lists the folder under `[tool.uv.workspace] exclude`, so `uv init` creates a
standalone project instead of adding it as a workspace member (see *Notes for this repository*).

> **TIP · ALWAYS CHECK --HELP FOR YOUR VERSION**
> mlx-lm moves quickly. This guide was written against its server options as of late 2026: `--model`, `--host`,
> `--port`, `--allowed-origins`, `--max-tokens`, `--temp`, `--top-p`, `--top-k`, `--min-p`, `--chat-template-args`,
> `--draft-model`, `--decode-concurrency`, `--prompt-concurrency`, `--prompt-cache-size`, `--prompt-cache-bytes`,
> `--log-level` and others. If a flag below isn't in your `--help`, leave it out.

> **WHY THIS MATTERS · WHY NOT INSTALL IT INTO THE WORKSPACE?**
> The workspace (Step 4) holds code that also runs in Linux containers and CI. MLX only runs on Apple Silicon.
> Keeping serving in its own project means one lockfile can never force Apple-only packages onto Linux machines, and
> you can upgrade mlx-lm without touching any service.

### 2 · Download the models and pin their revisions

```bash
uv run --project infra/model-serving hf auth whoami      # uses HF_TOKEN from the Keychain (Step 6, via direnv)
uv run --project infra/model-serving hf download mlx-community/Qwen3.8-27B-8bit
uv run --project infra/model-serving hf download lmstudio-community/Qwen3.6-35B-A3B-MLX-4bit
```

(`just models-download` runs the two downloads.)

> **WATCH OUT · USE THE EXACT REPOSITORIES YOU ALREADY RUN**
> You already run these models, so substitute your own repository IDs if they differ. Several conversions of
> Qwen3.6-35B-A3B exist (e.g. `mlx-community/…-4bit-DWQ`, `…-mxfp4`, `lmstudio-community/…-MLX-4bit`); this guide
> uses the lmstudio-community one as the example. Different conversions differ in speed and quality, so record which
> one you use. If they're already in your Hugging Face cache, the download just confirms them and finishes quickly.

Find the exact revision (commit) each download resolved to:

```bash
ls ~/.cache/huggingface/hub/models--mlx-community--Qwen3.8-27B-8bit/snapshots/
ls ~/.cache/huggingface/hub/models--lmstudio-community--Qwen3.6-35B-A3B-MLX-4bit/snapshots/
# each folder name is a 40-character commit SHA: the exact version you have
du -sh ~/.cache/huggingface/hub/models--*            # real size on disk
```

Record them in the model inventory, [`infra/model-serving/models.yaml`](../../infra/model-serving/models.yaml), the
seed of the model registry you'll build in Step 25. For each model it lists `id`, `repo`, `revision`, `upstream`,
`format`, `size_on_disk_gb`, `licence`, `port`, `role`, `approved_by` and `approved_on`. Replace the `<…>`
placeholders with your real SHAs, sizes, licence and name.

> **WHY THIS MATTERS · WHY PIN REVISIONS AND SERVE OFFLINE?**
> A model repository can be updated after you download it, with re-quantized weights or a fixed chat template. If the
> server silently fetched a new version, your evaluation scores could change with no code change at all. Recording
> the SHA, and serving with `HF_HUB_OFFLINE=1` (no network access to Hugging Face at all), means the model only
> changes when you decide it does, in a reviewed PR.

### 3 · Check how much memory the GPU may use

```bash
sysctl iogpu.wired_limit_mb                  # 0 means "macOS default"
uv run --project infra/model-serving python -c "
import mlx.core as mx
info = mx.device_info() if hasattr(mx, 'device_info') else mx.metal.device_info()
gb = 1024**3
print('total memory GB      :', round(info['memory_size'] / gb, 1))
print('GPU working-set limit:', round(info['max_recommended_working_set_size'] / gb, 1))
"
```

> **IN PLAIN ENGLISH · WHAT THIS TELLS YOU**
> By default macOS lets the GPU use only part of unified memory (on large-memory Macs, typically around two-thirds to
> three-quarters), keeping the rest for the system. Both models together need about 50 GB of weights plus KV cache,
> which fits under the default on a 128 GB Mac. Don't raise the limit unless measurements show you need to, e.g.
> when you add a judge model and run long contexts at the same time.

If you do need more later, the limit can be raised until the next reboot (example: leave about 16 GB for macOS):

```bash
# only if measurements show you need it
sudo sysctl iogpu.wired_limit_mb=112000      # ~109 GB for the GPU; resets on reboot
sudo sysctl iogpu.wired_limit_mb=0           # back to the default
```

> **WATCH OUT**
> Set it too high and macOS itself runs short of memory: heavy swapping, a frozen desktop, or a forced restart. Raise
> it in small steps, watch Activity Monitor → Memory → Memory Pressure, and keep it green or yellow. Record any change
> you make permanent in an ADR.

### 4 · Start each server, safely

Start them in two terminal windows first, so you can watch the logs. The `just` recipes (part 8) wrap these as
`just serve-quality` and `just serve-fast`.

Terminal 1, the quality model on :8081:

```bash
cd ~/dev/rag-platform
HF_HUB_OFFLINE=1 uv run --project infra/model-serving mlx_lm.server \
  --model mlx-community/Qwen3.8-27B-8bit \
  --host 127.0.0.1 --port 8081 \
  --max-tokens 4096 \
  --allowed-origins http://localhost \
  --log-level INFO
```

Terminal 2, the fast model on :8082 (thinking off by default):

```bash
cd ~/dev/rag-platform
HF_HUB_OFFLINE=1 uv run --project infra/model-serving mlx_lm.server \
  --model lmstudio-community/Qwen3.6-35B-A3B-MLX-4bit \
  --host 127.0.0.1 --port 8082 \
  --max-tokens 2048 \
  --chat-template-args '{"enable_thinking": false}' \
  --allowed-origins http://localhost \
  --log-level INFO
```

| Setting | Why |
|---|---|
| `--host 127.0.0.1` | Only this Mac can connect, never your Wi-Fi network. (It's the default, but say it explicitly.) Containers still reach it via `host.docker.internal` (Step 3). |
| `--port 8081` / `8082` | One fixed port per model, recorded in `models.yaml`. |
| `--max-tokens` | The server's default answer cap (512) is too short for real answers. |
| `--allowed-origins http://localhost` | The default `*` lets any website open in your browser send requests to your model. Restrict it. |
| `--chat-template-args` | Thinking off by default for the fast helper, where speed matters. The quality model keeps the model's default. |
| `HF_HUB_OFFLINE=1` | Never contact Hugging Face while serving: no silent updates, works without internet. |

> **WATCH OUT · TWO BUILT-IN LIMITATIONS TO RESPECT**
>
> - The mlx-lm documentation says its server is **not recommended for production**, because it only implements basic
>   security checks. It has **no authentication**: anything that can reach the port can use it.
> - A request's `model` field can make the server **load a different model** (any local path or Hugging Face ID),
>   which could exhaust memory.
>
> That's why these servers listen on localhost only, and why from Step 9 the LiteLLM gateway is the only client,
> sending the exact configured model ID.

### 5 · Talk to them

```bash
curl -s http://127.0.0.1:8081/health                        # {"status": "ok"}
curl -s http://127.0.0.1:8081/v1/models | jq '.data[].id'   # models the server can see

curl -s http://127.0.0.1:8082/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
        "messages": [
          {"role": "system", "content": "Rewrite the user question as a short search query."},
          {"role": "user", "content": "hey so what does our handbook say about working from home on fridays?"}
        ],
        "max_tokens": 64,
        "temperature": 0
      }' | jq -r '.choices[0].message.content, .usage'
```

Turn thinking on for a single request to the fast model, then compare the time taken and the `usage` token counts:

```bash
time curl -s http://127.0.0.1:8082/v1/chat/completions -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"A shop sells pens at 3 for $2. How much for 10 pens?"}],
       "max_tokens":1024, "chat_template_kwargs":{"enable_thinking":true}}' \
  | jq '{reasoning: .choices[0].message.reasoning, answer: .choices[0].message.content, usage: .usage}'
```

> **TIP · WHAT YOU SHOULD NOTICE**
> With thinking on, the answer takes longer and uses many more tokens, but the reasoning is visible and hard questions
> get more reliable answers. That's a cost/quality trade-off you'll decide per task: thinking off for rewriting and
> routing, often on for final answers to complex questions.

### 6 · Benchmark and record the real numbers

[`scripts/bench_models.py`](../../scripts/bench_models.py) is a dependency-free script (standard library only). For
each server it:

1. sends a tiny "Say hi." warm-up request (the first call loads weights into GPU memory, so it isn't measured);
2. sends the real prompt as a **streaming** chat completion (`"stream": true`, temperature 0, thinking off, up to 256
   tokens);
3. reads the Server-Sent Events stream line by line, notes the moment the first `content` or `reasoning` piece
   arrives (TTFT), and counts the pieces;
4. prints TTFT in seconds, approximate tokens per second (pieces ÷ streaming time) and the number of pieces.

`--long` swaps the short "Explain retrieval-augmented generation…" prompt for ~8k tokens of filler policy text plus
"Summarise the policy above in 5 bullet points.", so you can watch TTFT grow (prefill) and memory rise (KV cache).

```bash
uv run scripts/bench_models.py           # short prompt      (or: just bench)
uv run scripts/bench_models.py --long    # ~8k-token prompt  (or: just bench --long)
```

Measure **peak memory** for each model directly. mlx-lm's `generate` command prints it at the end:

```bash
HF_HUB_OFFLINE=1 uv run --project infra/model-serving mlx_lm.generate \
  --model mlx-community/Qwen3.8-27B-8bit --prompt "Explain RAG in 100 words." --max-tokens 200
# prints: Prompt: … tokens-per-sec · Generation: … tokens-per-sec · Peak memory: … GB
```

While both servers are loaded and the long benchmark runs, open Activity Monitor → Memory. Note each `python`
process's memory and the Memory Pressure graph. Then write everything down in
[`docs/benchmarks/models.md`](../benchmarks/models.md): machine, mlx-lm and macOS versions, date, then TTFT, ~tok/s
and peak memory for each model with the short and ~8k-token prompts, the memory pressure with both loaded, and a
conclusion (does the Step 3 budget hold? is the 24 GB container VM cap still right?).

> **TIP · READ THE NUMBERS LIKE AN ENGINEER**
>
> - Short-prompt tok/s tells you how fast answers stream.
> - Long-prompt TTFT tells you the cost of stuffing many retrieved chunks into a prompt. This becomes a key design
>   constraint in Projects 1, 8 and 15.
> - Expect the MoE fast model to stream several times faster than the dense 27B.
> - Run the benchmark twice, and record the second run (the first includes warm-up effects).

### 7 · Keep both servers running with launchd

Stop the two terminal servers (Ctrl + C). [`scripts/install-model-agents.sh`](../../scripts/install-model-agents.sh)
creates two launchd agents that start at login and restart after a crash. Given `QUALITY_MODEL` and `FAST_MODEL`, it:

- finds the repo root and the absolute path of `uv` (launchd doesn't load your shell's `PATH`);
- creates `~/Library/Logs/rag-platform/` and `~/Library/LaunchAgents/`;
- writes `~/Library/LaunchAgents/com.rag-platform.qwen-quality.plist` (port 8081, chat-template args `{}`) and
  `com.rag-platform.qwen-fast.plist` (port 8082, `{"enable_thinking": false}`), each running
  `uv run --project <repo>/infra/model-serving mlx_lm.server --model … --host 127.0.0.1 --port … --max-tokens 4096
  --allowed-origins http://localhost --chat-template-args …` with `HF_HUB_OFFLINE=1`;
- unloads any older version (`launchctl bootout`) and loads the new one (`launchctl bootstrap gui/<uid>`).

Example copies of the two generated files (with `/Users/you` and `/opt/homebrew/bin/uv` as the paths) are in
[`bootstrap/home/Library/LaunchAgents/`](../../bootstrap/home/Library/LaunchAgents/).

> **IN PLAIN ENGLISH · THE LAUNCHD SETTINGS**
>
> - `RunAtLoad`: start when you log in.
> - `KeepAlive`: restart the server if it ever stops.
> - `ThrottleInterval 30`: wait at least 30 seconds between restarts, so a broken server can't restart in a tight
>   loop.
>
> The logs go to `~/Library/Logs/rag-platform/`, where you can read them with `tail -f`, or in the Console app.

### 8 · just recipes, then commit with ADR-0007

The [`justfile`](../../justfile) gains three variables near the top (`quality_model`, `fast_model`, and `serve`,
the shared safe server command: `HF_HUB_OFFLINE=1 uv run --project infra/model-serving mlx_lm.server --host 127.0.0.1
--allowed-origins http://localhost`) and these recipes:

| Recipe | What it does |
|---|---|
| `just models-download` | Download both models (needs network + HF token) |
| `just serve-quality` | Run the quality server in the foreground on :8081, `--max-tokens 4096` (Ctrl+C to stop) |
| `just serve-fast` | Run the fast server in the foreground on :8082, `--max-tokens 2048`, thinking off |
| `just models-up` | Install / reload the always-on launchd services |
| `just models-down` | Remove both launchd services (frees the ~50 GB of memory) |
| `just models-health` | Check `/health` on both ports and print ok / DOWN |
| `just models-logs` | Follow the model server logs |
| `just bench [--long]` | Measure TTFT and tokens/s |

```bash
chmod +x scripts/install-model-agents.sh
just models-up
sleep 60 && just models-health     # first load reads ~50 GB from disk into memory: give it time
just bench
```

Then record the decision:

```bash
just adr "Serve local models natively with mlx-lm behind localhost"
```

[`docs/adr/0007-serve-local-models-natively-with-mlx-lm-behind-localhost.md`](../adr/0007-serve-local-models-natively-with-mlx-lm-behind-localhost.md)
says: serve Qwen3.8-27B-8bit on 127.0.0.1:8081 and Qwen3.6-35B-A3B-4bit on 127.0.0.1:8082 with `mlx_lm.server` from
the isolated, locked `infra/model-serving` project; record repos and revision SHAs in `models.yaml`; serve with
`HF_HUB_OFFLINE=1`; restrict CORS; keep both alive with launchd; from Step 9 the LiteLLM gateway is the only client;
benchmarks live in `docs/benchmarks/models.md`. It weighs Ollama, LM Studio, llama.cpp server, vllm-mlx and "one
model only", and says to revisit when concurrency outgrows mlx_lm.server's batching, a judge model is added, or
mlx-lm adds auth.

Add ADR-0007 to the ADR index, make sure `models.yaml` has the real SHAs and sizes and the benchmark table is filled
in, then:

```bash
git add -A
git commit -m "feat(models): serve qwen-quality and qwen-fast with mlx-lm, pinned and benchmarked"
git push -u origin feat/model-serving
gh pr create --fill && gh pr merge --squash --delete-branch
git switch main && git pull
```

*(Guide Figure 24: the model serving layer after this step. On the macOS host, as native processes on the Metal GPU,
the Hugging Face cache (`~/.cache/huggingface/hub`, pinned revisions, `HF_HUB_OFFLINE=1` when serving: no surprise
downloads) feeds two `mlx_lm.server` processes: qwen-quality on 127.0.0.1:8081 (careful answers, synthesis) and
qwen-fast on 127.0.0.1:8082 (routing, rewriting, quick replies). launchd keeps both running. Today curl and the
benchmark call them; from Step 9 LiteLLM is the only client, adding keys, limits and logging, because the servers
have no auth built in.)*

## Benefits

- Full GPU speed from native MLX on Apple Silicon, with no container overhead.
- The right model for each job: a fast MoE helper for high-volume small tasks and a dense model for quality, both
  behind the same standard API.
- Reproducible: locked server software, pinned model revisions, and offline serving.
- Measured, not guessed: TTFT, tokens/s and memory are recorded, and become the baseline for every later
  optimisation.
- Always on: launchd starts and restarts both servers, with logs in a standard place.
- Portable skills: the same OpenAI-compatible API, metrics and inventory practices apply to vLLM or TGI on cloud GPUs.

## Drawbacks and risks

- **Not production-grade serving.** No authentication, basic security, limited request validation. Localhost binding
  plus the gateway (Step 9) compensate, but the risk is real.
- **Memory is permanently committed.** Both models occupy about 50 GB+ while running, which limits other
  experiments. Stop one (`just models-down`) when you need the memory.
- **Model-switch risk.** A request naming another model can make the server load it. Only the gateway should talk to
  these ports.
- **Limited concurrency.** Batching exists, but it's less sophisticated than vLLM's continuous batching on GPUs. Fine
  for one developer; load testing comes in the Capstone.
- **A fast-moving dependency.** mlx-lm flags and behaviours change. That's why the version is locked, and why you
  upgrade deliberately with `uv lock --upgrade-package mlx-lm` and re-run the benchmark.
- **Quantization trade-off.** 4-bit is a little less accurate than 8-bit. The evaluation harness (Step 26) will
  measure whether that matters for each task.
- **Licences.** Each model has its own licence terms. Record them in the inventory and respect them.

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| **mlx-lm server (our choice)** | Apple's MLX library with a simple OpenAI-compatible server | Apple Silicon, MLX-format models, simple scripted setup |
| Ollama | Easy model runner (llama.cpp underneath) with its own library and automatic load/unload | Trying many models quickly; GGUF models; great developer experience |
| LM Studio | Desktop app with a model browser, MLX and GGUF engines, and a local server | You prefer a GUI, or are exploring models interactively |
| llama.cpp `llama-server` | Fast C++ engine, GGUF models, grammar-constrained output, many options | Cross-platform setups; features like grammars and GGUF quant variants |
| mlx-vlm server | MLX server for vision-language models (images + text) | Multimodal work (Step 35) |
| vllm-mlx and similar | MLX-based servers adding continuous batching and more API features | Higher concurrency on a Mac |
| vLLM / SGLang / TGI / TensorRT-LLM | Production GPU serving engines with continuous batching and paged KV cache | NVIDIA/AMD GPU servers in production (cloud mapping, Step 37) |
| Docker Model Runner | Docker's built-in model runner (models run natively, managed by Docker) | Teams standardised on Docker Desktop tooling |
| Hosted APIs (OpenAI, Anthropic, Bedrock, Vertex…) | Models served by a provider over the internet | Data may leave the machine, and you need frontier quality or zero ops |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Local RAG development on Apple Silicon | mlx-lm (this step), optionally Ollama for extra GGUF models |
| Exploring many models quickly | Ollama or LM Studio |
| Multimodal (image + text) models | mlx-vlm server (Step 35) |
| Many concurrent users on one Mac | An MLX server with continuous batching, or a llama.cpp server with parallel slots; load test first |
| Production on GPU servers | vLLM (or SGLang/TGI) behind a gateway, autoscaled |
| Strict data-sovereignty requirements | Self-hosted serving like this, never external APIs |

## Common mistakes

- **Binding to `0.0.0.0` "so containers can reach it".** Not needed: OrbStack forwards `host.docker.internal` to
  localhost (Step 3), and `0.0.0.0` exposes an unauthenticated model to your network.
- **Leaving CORS at `*`.** Any website in your browser could then use your models.
- **Measuring the first request.** It includes loading weights, so warm up first.
- **Comparing tok/s across different prompt lengths or thinking settings.** Keep tests identical.
- **Raising `iogpu.wired_limit_mb` blindly**, then wondering why macOS freezes. Measure first, raise in steps.
- **Downloading "latest" and never recording the revision.** Results become impossible to reproduce.
- **Letting several tools talk to the servers directly.** One client (the gateway) means one place for auth, limits
  and logs.
- **Forgetting the servers are running and using 50 GB of memory.** `just models-down` when you need it back.

## Done when

- [ ] `infra/model-serving` exists with its own `pyproject.toml` and `uv.lock` (mlx-lm and the Hugging Face CLI)
- [ ] Both models are downloaded; `models.yaml` lists repo, revision SHA, size, licence, port and role
- [ ] You know your GPU working-set limit, and whether you needed to change it
- [ ] `just models-up` then `just models-health` shows both ok after loading
- [ ] `curl` chat requests work on both ports, and you compared thinking on vs off
- [ ] `docs/benchmarks/models.md` has real TTFT, tok/s and peak-memory numbers (short and ~8k prompts)
- [ ] Logs appear in `~/Library/Logs/rag-platform/`, and the servers restart automatically after a crash
- [ ] Servers listen on 127.0.0.1 only (`lsof -nP -iTCP -sTCP:LISTEN | grep -E '8081|8082'`)
- [ ] ADR-0007 and all files are merged through a PR

## Recap

> **RECAP**
> Your Mac now runs a real model serving layer: a careful 27B writer on `:8081` and a fast MoE helper on `:8082`.
> Both are OpenAI-compatible, pinned to exact revisions, served offline, bound to localhost, kept alive by launchd,
> and measured. You understand prefill vs decode, TTFT vs tokens/s, the KV cache, quantization, MoE and thinking
> mode: the vocabulary of every serving decision ahead. Next, the embedding and reranker models that power search.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `infra/model-serving/pyproject.toml` | The isolated serving project: depends on `mlx-lm` and `huggingface_hub[cli]`, outside the workspace. |
| `infra/model-serving/uv.lock` | Locks mlx-lm, MLX and the Hugging Face CLI to exact versions, so the server software only changes on purpose. |
| `infra/model-serving/models.yaml` | The model inventory: repo, revision SHA, upstream, format, size, licence, port, role and approval for each model. |
| `pyproject.toml` (changed) | Excludes `infra/model-serving` from the uv workspace; mypy now also checks `scripts/` and `tests/`. |
| `scripts/install-model-agents.sh` | Writes and loads the two launchd agents that keep the servers running, with logs in `~/Library/Logs/rag-platform/`. |
| `bootstrap/home/Library/LaunchAgents/com.rag-platform.qwen-quality.plist` | Reference copy of the generated launchd agent for the quality model (:8081). |
| `bootstrap/home/Library/LaunchAgents/com.rag-platform.qwen-fast.plist` | Reference copy of the generated launchd agent for the fast model (:8082, thinking off). |
| `justfile` (changed) | Model variables plus `models-download`, `serve-quality`, `serve-fast`, `models-up`, `models-down`, `models-health`, `models-logs` and `bench`. |
| `scripts/bench_models.py` | Measures TTFT, ~tokens/s and streamed pieces for both servers, with an optional ~8k-token prompt. |
| `docs/benchmarks/models.md` | The results table you fill in with your machine's real numbers. |
| `tests/test_bench_models.py` | Tests the benchmark against a fake streaming server (no GPU needed). |
| `tests/test_install_model_agents.py` | Runs the installer with stand-in `uv`/`launchctl` and checks the generated plists; also checks the reference copies. |
| `docs/adr/0007-serve-local-models-natively-with-mlx-lm-behind-localhost.md` | ADR-0007: the serving decision, alternatives and consequences. |
| `docs/adr/README.md` (changed) | ADR-0007 added to the index. |
| `docs/steps/step-07-model-serving-mlx-lm.md` | This write-up. |

## Notes for this repository

- **Workspace exclude.** In this repository the root `pyproject.toml` declares a uv workspace (`members =
  ["libs/*"]`). Running the guide's `uv init` inside `infra/model-serving` would otherwise *add* the folder as a
  workspace member and put MLX into the shared `uv.lock`, the exact thing the step wants to avoid. So the root now has
  `exclude = ["infra/model-serving"]`, and the serving project keeps its own `uv.lock`. The root lockfile is unchanged.
- **Machine-specific values stay as placeholders.** The revision SHAs, sizes on disk, licence confirmation and
  approver in `models.yaml`, and every number in `docs/benchmarks/models.md`, can only come from your Mac after the
  ~50 GB download. They are committed as the guide's `<…>` placeholders; fill them in on the Mac before merging, as
  the chapter says.
- **launchd plists.** The real agents live in `~/Library/LaunchAgents/` and are generated by
  `scripts/install-model-agents.sh` (they contain absolute paths to your repo, your `uv` and your home folder). The
  copies under `bootstrap/home/Library/LaunchAgents/` show the exact output for an example user `you` with Homebrew's
  `uv`; they are for reading and review, not to be copied by hand.
- **`huggingface_hub[cli]`.** The dependency is written exactly as the guide gives it. In huggingface-hub 2.x the
  `hf` command is part of the base package and the `cli` extra no longer exists, so uv prints a harmless
  "does not have an extra named `cli`" warning when it resolves the project.
- **What was validated here (Linux, no Apple GPU).** mlx-lm only runs on Apple Silicon, so the servers were not
  started. The lockfile was resolved for all platforms (`uv lock --locked --project infra/model-serving` passes) and
  `uv run --project infra/model-serving hf version` works; every flag used (`--model`, `--host`, `--port`,
  `--max-tokens`, `--allowed-origins`, `--chat-template-args`, `--log-level`) was confirmed in mlx-lm 0.32.0's
  `server.py`, as were the `/health` endpoint, per-request `chat_template_kwargs` and the `reasoning` field. The
  benchmark and installer have unit tests (fake SSE server; fake `launchctl`), the plists were parsed with
  `plistlib`, the shell script passed `bash -n`, the YAML parses, and `just --dry-run` shows the expected commands.
- **Tests and typing.** The benchmark and the installer test are new Python files, so the root mypy configuration
  now also covers `scripts/` and `tests/` (strict), and both pass ruff.
