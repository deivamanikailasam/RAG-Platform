# Glossary

Plain-English definitions of the terms introduced across the build guide, in alphabetical order.
The number in brackets is the step where the term first appears; see [`docs/steps/`](steps/README.md).

| Term | Meaning | Step |
|---|---|---:|
| 0.0.0.0 / * | "Every interface": a port bound here is reachable by anyone who can reach your machine on the network. | 3 |
| Active parameters | In a Mixture of Experts model, the parameters actually used for each token (about 3B in Qwen3.6-35B-A3B, the "A3B"); they set the speed. | 7 |
| ADR (Architecture Decision Record) | A short Markdown file recording one significant decision: context, decision, alternatives and consequences. | 4 |
| age | A small, modern encryption tool with short keys (`age1…`); makes the key pair SOPS uses. A simpler, safer replacement for GPG. | 6 |
| Analytics | Anonymous usage statistics a tool sends back to its makers. | 1 |
| arm64 / aarch64 vs amd64 / x86_64 | Processor families; Apple Silicon is arm64, amd64-only images need slower emulation. | 3 |
| Asymmetric retrieval | Embedding questions and documents differently (queries get a task instruction, documents don't), because a short question and a long passage are different kinds of text. | 8 |
| Auto-fix | A check that changes files to fix the problem itself; you review the change and `git add` it again. | 5 |
| Batch | Several texts sent together and embedded in one GPU pass; much faster per text than one at a time. | 8 |
| Bi-encoder | A model (the embedder) that turns the query and each document into vectors separately, so document vectors can be computed once in advance and compared in milliseconds. | 8 |
| Bind mount | A host folder shared into a container; fine for config and code, slow for databases on a Mac. | 3 |
| Branch | A separate line of work (a draft) where you change things without touching `main`. | 4 |
| Branch protection / ruleset | GitHub settings that block direct pushes to `main` and require PRs, checks and signed commits. | 4 |
| Brewfile | A plain text file listing Homebrew formulas and casks; `brew bundle` installs everything in it. | 1 |
| Cask | A Homebrew package that is a normal Mac app with a window. | 1 |
| Chat template | The model-specific recipe that turns a list of messages into the exact text format the model was trained on. | 7 |
| Ciphertext | The scrambled, encrypted version of a value; unreadable without the right key. | 6 |
| CLI | Command-line interface: a program you control by typing commands. | 1 |
| CODEOWNERS | A GitHub file naming who must review changes to which folders. | 4 |
| Command Line Tools | Apple's free kit of basic developer programs: compiler, `make`, `git`, system headers. | 1 |
| Commit | A save point in git history, with a message explaining what changed and why. | 4 |
| Compiler | A program that turns human-written source code into a program the computer can run. | 1 |
| Compose project | The group of containers, networks and volumes one Compose file starts, sharing a name (`name: rag-platform`) that prefixes every container (`rag-platform-litellm-1`). | 9 |
| Container | A running copy of an image: a self-contained "apartment" with a program and everything it needs. | 3 |
| Container runtime | The software that downloads images and runs containers (OrbStack, Docker Desktop, Colima, Podman). | 3 |
| Context window | The maximum number of tokens (prompt + answer) a model can handle at once. | 7 |
| Conventional Commits | A commit-message format `type(scope)!: description` (e.g. `feat(gateway): …`) readable by people and tools. | 4 |
| CORS | Browser rules for which websites may call a server from inside a web page; too open (`*`) and any site you visit could call your local model. | 7 |
| Cosine similarity | A score for how closely two vectors point the same way: near 1 = very similar meaning, near 0 = unrelated. For unit-length vectors it equals the dot product. | 8 |
| Cross-encoder | A model (the reranker) that reads the query and one document together and scores their relevance; precise but slow, so only used on a shortlist. | 8 |
| Data key | The random key SOPS creates per file to lock every value; it is itself locked once per recipient. | 6 |
| Decode | The second phase of generation: the model writes the answer one token at a time; its speed is limited by memory bandwidth. | 7 |
| Dependency | A package your project needs in order to work. | 2 |
| Dependency group | A named set of extra dependencies in `pyproject.toml` (PEP 735), e.g. `dev` for test tools not needed in production. | 2 |
| Deployment (LiteLLM) | One real backend behind a model alias; an alias can have several, for load-balancing or failover. | 9 |
| Dev dependency | A package needed only while developing (e.g. pytest), not when the app runs in production. | 2 |
| Dimensions (of an embedding) | How many numbers an embedding vector has (Qwen3-Embedding-0.6B: up to 1,024); more can hold more nuance but costs storage and search time. | 8 |
| direnv | A tool that loads a project's settings automatically when you enter its folder. | 1 |
| Docker Compose | A file (`compose.yaml`) listing many containers and how they connect; `docker compose up` starts them all. | 3 |
| Docker engine / CLI | The engine runs containers inside the VM; the `docker` command is how you talk to it. | 3 |
| Drift | When the dependency list (`pyproject.toml`) and the lockfile (`uv.lock`) no longer match; `uv sync --locked` catches it. | 2 |
| EditorConfig | A small `.editorconfig` file telling every editor the same formatting basics (indentation, line endings). | 4 |
| Embedding / vector | A fixed-length list of numbers representing a text's meaning: a point in meaning space. | 8 |
| Embedding contract | Everything that defines how vectors were made (model + revision, dimensions, query instruction, normalisation, pooling, chunk limit); change any part and the index must be rebuilt. | 8 |
| Encryption | Scrambling data so only someone with the right key can unscramble it. | 6 |
| Endpoint | A specific URL path on a server, e.g. `/v1/chat/completions` or `/health`. | 7 |
| Envelope encryption | Values are locked with a random data key, and the data key is locked separately for each recipient, so adding a person never means re-encrypting every value by hand. | 6 |
| Environment variable | A named value handed to a program when it starts (`DB_PASSWORD=…`); fine for settings, easy to leak for secrets. | 6 |
| False positive | A check flags something that is actually fine; silence it narrowly, with a comment explaining why. | 5 |
| Formatter | A tool (e.g. `ruff format`) that rewrites code layout into one consistent style without changing what it does. | 5 |
| Formula | A Homebrew package that is a command-line tool. | 1 |
| Gateway (AI / LLM gateway) | A server in front of all model servers: every request passes through it for authentication, allow-listing, routing, limits and logging. | 9 |
| Git hook | A script git runs automatically at a set moment: before a commit, after the message is written, before a push. | 5 |
| .gitattributes | Rules for how git treats file types (line endings, binary files, generated files). | 4 |
| .gitignore | A "do not pack" list of files git must never track (secrets, `.venv`, data, models). | 4 |
| Hash | A short fingerprint calculated from a file's contents; change one byte and it changes completely. | 2 |
| Healthcheck | A command Compose runs inside a container every few seconds to ask "are you working?"; failures mark it unhealthy. | 9 |
| Homebrew | The standard package manager ("app store for developer tools") on macOS. | 1 |
| host.docker.internal | The address a container uses to reach programs running on the host Mac itself. | 3 |
| Image | The frozen blueprint a container is started from: a program plus all its dependencies. | 3 |
| Image tag vs digest | A tag (`v1.104.0`) is a movable label; a digest (`@sha256:…`) is the exact, unchangeable fingerprint of one image. | 9 |
| Infrastructure as code | Defining your environment in version-controlled files instead of setting it up by hand. | 1 |
| Interpreter | The `python` program itself: the engine that reads and runs Python code, e.g. CPython 3.12. | 2 |
| justfile | A menu of named command shortcuts run with `just <recipe>` (e.g. `just check`), reused by CI. | 4 |
| Key pair (public / private key) | Two matching keys: anyone can lock with the public key, only the private key unlocks. Share the public one, guard the private one. | 6 |
| KV cache | The model's working memory of everything read so far; grows with prompt and answer length and is a big part of memory use. | 7 |
| launchd | macOS's built-in service manager: starts programs at login and restarts them if they crash (agents live in `~/Library/LaunchAgents/`). | 7 |
| Linter / static analysis | A tool (e.g. `ruff check`) that reads code without running it and flags likely bugs and risky patterns, each as a coded rule like `B006`. | 5 |
| Liveness / readiness | Two health questions: "is the process alive?" (restart it if not) and "can it serve traffic yet?". | 9 |
| localhost / 127.0.0.1 | "This machine only": a port bound here is reachable only from your own Mac. | 3 |
| Lockfile | A file recording the exact version and hash of every package in the full dependency tree (`uv.lock`). | 2 |
| Log rotation | Keeping only the newest few log files of a limited size and deleting the oldest (here 3 × 10 MB). | 3 |
| macOS Keychain | The Mac's built-in encrypted password store, unlocked by your login; home for personal tokens. | 6 |
| Master key | The gateway's root credential (`LITELLM_MASTER_KEY`); it can do everything, so it is for admins only. | 9 |
| Matryoshka embeddings | Embeddings trained so their first part is already a useful smaller embedding; keep the first N numbers, re-normalise, and save storage at a small quality cost. | 8 |
| MDM | Mobile Device Management: how company IT installs and controls software on employees' Macs (e.g. Jamf, Kandji). | 1 |
| Meaning space | The many-dimensional map an embedding model places texts on, where similar meanings sit close together. | 8 |
| Memory bandwidth | How fast data moves between memory and the GPU; each decoded token reads the model's weights, so it is the speed limit for tokens per second. | 7 |
| Mixture of Experts (MoE) | A model that stores many specialist sub-networks but uses only a few per token: memory like a big model, speed like a small one. | 7 |
| Model alias (model group) | The public role name clients use, such as `qwen-fast`; LiteLLM calls it `model_name`. | 9 |
| Model inventory | A reviewed list of which exact models a platform serves: repo, revision, licence, port, role and who approved it (`infra/model-serving/models.yaml`). | 7 |
| Model revision | The exact git commit (40-character SHA) of a model repository on Hugging Face; the same name isn't always the same model. | 7 |
| Monorepo | One repository holding all services, libraries, infrastructure and docs. | 4 |
| Named volume | Docker-managed storage inside the VM that survives container deletion; use it for database data. | 3 |
| Network interface | A way your machine connects to networks: Wi-Fi, Ethernet, or localhost. | 3 |
| no-new-privileges | A container security option that stops any process inside it gaining extra privileges, e.g. through setuid programs. | 9 |
| --no-verify | A git flag that skips local hooks; the reason CI must repeat the same checks. | 5 |
| Normalisation | Scaling a vector to length 1, so cosine similarity becomes a simple dot product. | 8 |
| OpenAI-compatible API | The same request and response format as OpenAI's API, so any tool that speaks "OpenAI" can call a local model. | 7 |
| OrbStack | A lightweight macOS container runtime: Linux VM + Docker engine + Compose + single-node Kubernetes. | 3 |
| Package manager | A program that installs, updates and removes other software and tracks what's installed. | 1 |
| PATH | The ordered list of folders your shell searches when you type a command. First match wins. | 1 |
| PEP | Python Enhancement Proposal: an official Python standard (e.g. PEP 621 `pyproject.toml`, PEP 735 dependency groups, PEP 668 protected system Pythons). | 2 |
| Plaintext | Readable, unencrypted text. | 6 |
| Polyrepo | One repository per service or library. | 4 |
| Pooling | How an embedding model squeezes its per-token outputs into one vector (Qwen3-Embedding uses the last token). | 8 |
| Port | A numbered "door" through which a program accepts network connections, e.g. 5432 for Postgres. | 3 |
| pre-commit (the tool) | A framework that installs and runs git hooks from one file, `.pre-commit-config.yaml`. | 5 |
| Prefill | The first phase of generation: the model reads every prompt token in one parallel pass; limited by compute, it sets TTFT. | 7 |
| Prompt cache | Reusing the KV cache of a prompt start sent before (e.g. the same system prompt), which makes TTFT much faster. | 7 |
| Provider prefix | The part of a LiteLLM `model` before the first `/` (e.g. `openai/`): which API protocol to speak to the backend. | 9 |
| Pull request (PR) | A request to review a branch and merge it into `main`. | 4 |
| Push / pull | Send your commits to the remote / fetch other people's commits from it. | 4 |
| pyproject.toml | The standard Python project file listing the dependency ranges you'll accept (PEP 621). | 2 |
| Quantization | Storing each of a model's numbers in fewer bits (8-bit, 4-bit): smaller and faster, at the cost of a little accuracy. | 7 |
| Query instruction | A one-sentence task description prefixed to queries (not documents) for instruction-aware embedders: `Instruct: {task}\nQuery:{query}`. | 8 |
| Re-indexing | Re-embedding every stored document because the embedding contract changed; planned like a migration. | 8 |
| Recipient | Someone (or a machine) whose public key can open a SOPS file: you, CI, a teammate. | 6 |
| Remote / origin | A copy of the repository on a server (GitHub); `origin` is its default nickname. | 4 |
| Repository | The project's filing cabinet: all files plus their full history of changes (git). | 4 |
| Restart policy | The rule Docker uses to restart a container that stops or crashes (`restart: unless-stopped`). | 9 |
| Retrieve-then-rerank | The two-stage search pattern: a fast embedder finds ~50 candidates, then a slow, precise reranker picks the best few for the LLM. | 8 |
| Reverse proxy | A server that sits in front of other servers, receives every request, applies rules and forwards it. | 9 |
| Revocation | Making an old secret stop working, e.g. deleting an API token. | 6 |
| Rotation | Replacing a secret with a new value on a schedule, or immediately after a suspected leak. | 6 |
| Routing | Choosing which real backend (deployment) answers a request for a given model alias. | 9 |
| Secret | Any value that grants access: a password, API key, token, private key or encryption key. | 6 |
| Secret file / /run/secrets | A secret delivered to a container as a small in-memory file, the standard Docker and Kubernetes pattern. | 6 |
| Secret scanner | A check (e.g. gitleaks, detect-private-key) that looks for keys, tokens and passwords before they are committed. | 5 |
| SecretStr | A pydantic type that prints as `**********`; the real value needs a deliberate `.get_secret_value()`. | 6 |
| Semantic Versioning | MAJOR.MINOR.PATCH version numbers: breaking change → major, `feat` → minor, `fix` → patch. | 4 |
| Shell / zsh | The program inside Terminal that reads and runs your commands; zsh is the macOS default. | 1 |
| Shift left | Moving checks earlier in the process (editor, commit) where fixing problems is cheapest. | 5 |
| Signed commit | A commit stamped with your private key so GitHub can show it as Verified (really from you). | 4 |
| SOPS | "Secrets OPerationS": encrypts the values in YAML, JSON or `.env` files while leaving the names readable. | 6 |
| Speculative decoding | A small draft model guesses a few tokens ahead and the big model checks them in one pass, speeding up decoding (`--draft-model`). | 7 |
| Squash merge | Merging a PR so all its small commits become one clean commit on `main`. | 4 |
| src layout | Putting a package's code under `src/<name>/` so tests import the installed package, not the raw folder. | 4 |
| SSDLC | Secure Software Development Lifecycle: building security checks (static analysis, secret scanning) into every change. | 5 |
| SSH key | A private key that stays on your Mac and a public `.pub` key you give GitHub, to prove it's you without a password. | 4 |
| Staged files | The files you have `git add`-ed: exactly what the next commit will contain, and what hooks check. | 5 |
| Streaming (SSE) | Sending an answer token by token as it is generated, over Server-Sent Events, instead of all at the end. | 9 |
| Supersede | Replace an accepted ADR with a newer ADR that points back to it; the old one is never edited. | 4 |
| TEI (Text Embeddings Inference) | Hugging Face's Rust server for embedding and reranking models, with batching, API keys and metrics; runs natively with Metal on Apple Silicon. | 8 |
| Thinking mode | Qwen models' optional hidden reasoning before the answer; better on hard questions, slower and more tokens (`enable_thinking`). | 7 |
| Throughput | How much work a server finishes per second, e.g. chunks embedded per second. | 8 |
| Token | The unit a model reads and writes: roughly ¾ of an English word. | 7 |
| Tokenizer | The model's dictionary for converting text to tokens and back. | 7 |
| Tokens per second (tok/s) | How fast an answer streams once it starts; mostly set by memory bandwidth. | 7 |
| Transitive dependency | A dependency of a dependency: a package you never chose that comes along because one you chose needs it. | 2 |
| Truncation / max sequence length | The longest text a model reads; anything beyond is cut off, silently in TEI by default (`--auto-truncate`). | 8 |
| Trunk-based development | `main` (the trunk) is always working; every change goes through a short-lived branch and a PR. | 4 |
| TTFT (time to first token) | How long you wait before the first word appears; mostly set by prefill and prompt length. | 7 |
| Type checker | A tool (e.g. `mypy`) that reads type hints and checks they are used consistently, catching wrong-kind-of-value bugs before running. | 5 |
| Type hint | A label saying what kind of value a variable or function expects or returns, e.g. `def chunk(text: str) -> list[str]`. | 5 |
| Unified memory | Apple Silicon memory shared by the CPU and GPU; every GB given to the container VM is a GB the models lose. | 3 |
| uv | Astral's all-in-one Python tool: interpreters, virtual environments, locking and tool installs. | 2 |
| Virtual environment | A private folder of packages (`.venv`) for one project, tied to one interpreter. | 2 |
| Virtual key | A per-app or per-person key issued by the gateway, with its own budget, limits and allowed models; needs a database (Step 10). | 9 |
| Virtual machine (VM) | A computer simulated inside your computer; on a Mac, containers run inside a small Linux VM. | 3 |
| Wheel | A pre-built Python package, ready to install, like flat-pack furniture. | 2 |
| Wired memory / GPU working-set limit | The share of unified memory macOS lets the GPU lock for itself (`iogpu.wired_limit_mb`); large models need it big enough. | 7 |
| Workspace (uv) | Several Python packages in one repository sharing one `uv.lock` and one `.venv`. | 4 |
