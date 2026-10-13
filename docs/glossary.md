# Glossary

Plain-English definitions of the terms introduced across the build guide, in alphabetical order.
The number in brackets is the step where the term first appears; see [`docs/steps/`](steps/README.md).

| Term | Meaning | Step |
|---|---|---:|
| 0.0.0.0 / * | "Every interface": a port bound here is reachable by anyone who can reach your machine on the network. | 3 |
| 401 vs 403 | 401 Unauthorized means "I don't know who you are" (no token, or a bad one); 403 Forbidden means "I know who you are, and the answer is no" (a valid token without the needed role). | 17 |
| ABAC (attribute-based access control) | Access rules based on facts (attributes) about the person and the thing, such as classification, clearance or department, rather than just roles; what OPA evaluates here. | 18 |
| Abstention | Saying "I don't know" when the sources don't contain the answer; a correct answer, not a failure. Here it happens without a model call when search finds nothing, and when the model says so or (with `uncited: abstain`) cites nothing. | 33 |
| Access token | The short-lived (5-minute) token an app shows to an API on every call; it carries who you are, your groups and roles, and when it expires. | 16 |
| Acknowledgement (XACK) | A worker's "done" signal for a stream message. Until it arrives, the message stays pending for that worker. | 15 |
| ACL (access control list, Valkey) | Per-user rules for which keys (`~pattern`), pub/sub channels (`&pattern`) and commands (`+@category`, `-@category`) a user may use; `user default off` disables anonymous access. | 15 |
| Action (GitHub) | A reusable workflow step published by someone else (`actions/checkout`): third-party code that runs inside your job with its token, so it is pinned by commit SHA. | 27 |
| Active parameters | In a Mixture of Experts model, the parameters actually used for each token (about 3B in Qwen3.6-35B-A3B, the "A3B"); they set the speed. | 7 |
| Adaptive RAG, query routing | Choosing a strategy per question (no retrieval for small talk, one search, or several for a compound question) instead of spending the same effort on every question; the `adaptive` architecture. | 35 |
| Admin events (Keycloak) | Keycloak's record of every administrative change (user created, group membership added, lockout cleared), with the full details when enabled; audit evidence for "who changed what". | 16 |
| Admission control | Checks the Kubernetes API server runs on every object (after authentication and authorization, before storing it); mutating admission fills defaults, validating admission refuses what breaks the rules. | 29 |
| ADR (Architecture Decision Record) | A short Markdown file recording one significant decision: context, decision, alternatives and consequences. | 4 |
| Advanced / modular RAG | Naive RAG plus improvements before retrieval (query rewriting), during it (hybrid search, fusion) and after it (reranking, filtering), built from swappable modules; the `standard` architecture. | 35 |
| age | A small, modern encryption tool with short keys (`age1…`); makes the key pair SOPS uses. A simpler, safer replacement for GPG. | 6 |
| Agentic RAG, ReAct | A model decides, step by step, which tool to use next (here: which search), reasoning from what it has found so far; ReAct (reason + act) is the common prompting pattern for it. The `agentic` architecture. | 35 |
| Alert rule | A PromQL condition Prometheus checks every evaluation; when it has stayed true for the rule's `for` duration, the alert fires and goes to Alertmanager with its labels (e.g. `severity`) and annotations (summary, runbook). | 20 |
| Alertmanager | The service that receives firing alerts from Prometheus and decides what to do with them: group, de-duplicate, silence, inhibit and route each to the right receiver (a page, a ticket, a chat channel). | 20 |
| `alg: none` | A token header claiming the token is unsigned. Some old libraries accepted such tokens as valid, a famous vulnerability; our verifier never does. | 17 |
| Algorithm allow-list | The fixed list of signing algorithms a verifier accepts (only `RS256` here), chosen by the server, never by the token, so an attacker can't pick a weaker one. | 17 |
| Algorithm confusion | An attack that re-signs a token with HS256 using the server's PUBLIC key as the HMAC password; blocked by allowing only RS256. | 17 |
| Alias (Qdrant) | A stable name (`rag_chunks`) pointing at a real collection; applications use it, and it can be switched to another collection instantly and atomically. | 12 |
| Allow-list | The only models a key may use; a request for anything else is refused (401/403). | 10 |
| Analysis run | The checks Argo Rollouts runs while a canary is live: Prometheus queries and a Job, each one pass or fail; a failure aborts the release. | 37 |
| Analytics | Anonymous usage statistics a tool sends back to its makers. | 1 |
| Analyzer | The recipe a search engine uses to turn text into searchable terms: a tokenizer plus token filters (lowercase, synonyms, stemming). | 13 |
| Anchoring (audit log) | Copying the newest hash of a chain (and the events) somewhere the database's administrators can't change, such as an object-locked bucket, so a later rewrite of the chain becomes visible. | 23 |
| ANN (approximate nearest neighbour) | Finding nearly the closest vectors very fast, instead of exactly the closest by checking every one. | 11 |
| Annotation (Grafana) | A marker drawn on Grafana graphs at the moment something happened, such as a new prompt version going live, so you can see whether quality or latency changed then. | 24 |
| API server (Kubernetes) | The cluster's front desk: every change, from `kubectl` or Argo CD, goes through it and is checked there. | 29 |
| App of apps | One Argo CD Application (`deploy/argocd/root.yaml`) whose folder holds the other Applications; adding an app is a pull request. | 29 |
| Append-only | Rows may be added, never changed or removed; enforced here by a trigger that refuses `UPDATE`, `DELETE` and `TRUNCATE`, even for the table's owner. | 23 |
| Application (Argo CD) | Argo CD's "this folder of git, at this revision, goes to that namespace", kept in sync automatically. | 29 |
| AppProject (Argo CD) | Argo CD's permission boundary: which repository, namespaces and kinds of objects its Applications may touch. | 29 |
| AppRole (role ID, secret ID) | OpenBao's login method for machines: the role ID says which role (like a username, not secret); the secret ID is the password. rag-api's agent gets its secret ID wrapped and single-use. | 28 |
| Argo CD | A CNCF-graduated GitOps controller with a web UI: it pulls git and makes the cluster match it, continuously. | 29 |
| arm64 / aarch64 vs amd64 / x86_64 | Processor families; Apple Silicon is arm64, amd64-only images need slower emulation. | 3 |
| Asymmetric retrieval | Embedding questions and documents differently (queries get a task instruction, documents don't), because a short question and a long passage are different kinds of text. | 8 |
| At-least-once delivery | Every job is delivered at least once, but may be delivered twice after a crash (the worker finished but died before acknowledging). | 15 |
| Attestation | A signed statement about an artefact, attached to its digest: for example its build provenance (which repo, commit, workflow and runner built it) or its SBOM. | 27 |
| Attributes (span) | Key–value facts recorded on a span, e.g. `rag.candidates = 5`; facts about the request, never its content. | 19 |
| Audience (`aud`) | The claim saying who a token is meant for (here `rag-api`). An API must reject tokens meant for someone else. | 16 |
| Audit device (OpenBao) | Where OpenBao records every request and response, one JSON line each, with secret values replaced by HMACs. Declared in server.hcl; if no audit device can write, OpenBao refuses to answer. | 28 |
| Audit log | A permanent, minimal record of security-relevant actions (who, what, when, result), kept for years and protected from tampering. Not for debugging. | 23 |
| Augmentation, grounding | Adding retrieved documents to the prompt so the model answers from them, not from its own memory; the "A" in RAG. | 33 |
| Auth method | How a client proves who it is to OpenBao (AppRole, userpass, OIDC, Kubernetes…). Success gives a token with policies attached. | 28 |
| Authentication vs authorisation | Who are you? (sign-in) versus what may you do? (permissions). Keycloak does the first and carries the facts (groups, roles) for the second. | 16 |
| Authorisation policy | The written rules that say who may do which action and see which things; here `policies/rag/authz/authz.rego` plus its `data.json`. | 18 |
| Authorization code + PKCE | The sign-in flow for web apps: the browser gets a one-time code and swaps it for tokens, proving with a random "code verifier" (PKCE) that it is the same app that started the sign-in. | 16 |
| Authorization header | The HTTP request header that carries credentials; for APIs it is `Authorization: Bearer <access token>`. | 17 |
| Auto-auth | The OpenBao Agent feature that logs in by itself (here with AppRole), renews its token and logs in again when the token reaches its maximum age. | 28 |
| Auto-fix | A check that changes files to fix the problem itself; you review the change and `git add` it again. | 5 |
| Backup receipt | A small JSON file written next to a database dump: its SHA-256 checksum, size, time and the row counts of the important tables, so a restore can be checked against it. | 36 |
| Baseline (evaluation) | The summary of the last accepted evaluation run, committed in `evals/baselines/`; a new run mustn't fall below it by more than a small tolerance. | 26 |
| Blue/green re-index | Rebuilding the search index into a new collection beside the live one, comparing the two, then switching by a one-line change; the old collection stays until the switch is proven. | 36 |
| Boilerplate | Text that repeats everywhere and means nothing (running headers, footers, "Page 3 of 9", cookie banners); removed before chunking so it doesn't match every search. | 31 |
| Break glass | The recorded emergency path around the normal rules, e.g. `just promote prod sha256:… "INC-1234: why"` skips the gates but writes the reason into the commit and still needs review. | 37 |
| Break-glass | Emergency super-powers (here the database superuser), used rarely, deliberately and visibly. | 23 |
| B-tree | The default Postgres index, for exact values and ranges (an ID, a date); like a sorted phone book. | 11 |
| Batch | Several texts sent together and embedded in one GPU pass; much faster per text than one at a time. | 8 |
| Bearer token | A token that works for whoever holds ("bears") it, sent as `Authorization: Bearer <token>`. Guard it like a password and never log it. | 17 |
| Bi-encoder | A model (the embedder) that turns the query and each document into vectors separately, so document vectors can be computed once in advance and compared in milliseconds. | 8 |
| Bind mount | A host folder shared into a container; fine for config and code, slow for databases on a Mac. | 3 |
| Blast radius | How much damage one leaked or misbehaving credential can do; small, scoped, expiring keys keep it small. | 10 |
| Blue/green | Building the new version beside the old one, then switching traffic all at once, with the old one kept for rollback. | 12 |
| BM25 | The standard keyword relevance formula: scores rise with how often query words appear in a document (term frequency), how rare they are overall (inverse document frequency) and how short the document is, with diminishing returns for repeats. | 13 |
| Bootstrap (temporary) admin | The first Keycloak administrator created at start-up from environment variables (`temp-admin`), only to create a real, MFA-protected admin and then be deleted. | 16 |
| Branch | A separate line of work (a draft) where you change things without touching `main`. | 4 |
| Branch protection / ruleset | GitHub settings that block direct pushes to `main` and require PRs, checks and signed commits. | 4 |
| Break-glass (OpenBao) | The documented emergency path when the admin login is lost: `bao operator generate-root` with 2 of the 3 key shares, used once, then revoked and recorded. | 28 |
| Brewfile | A plain text file listing Homebrew formulas and casks; `brew bundle` installs everything in it. | 1 |
| Brute-force protection | Temporarily locking an account after several wrong passwords (here 5), with a wait that grows from 60 seconds to 15 minutes. | 16 |
| Bucket / key / object (S3) | A top-level container in object storage / the object's name, which can look like a path but is just a string (`raw/remote.pdf`) / the bytes plus metadata. | 14 |
| Bucket (histogram) | One counter in a histogram: how many values were at or below a fixed edge (`le="0.5"`, `le="2"`…). The edges must be in the metric's unit and should include each objective (2 s here). | 20 |
| Budget / budget period | The maximum spend (here in shadow dollars) a key or team may reach before requests are refused, and how often it resets (e.g. `30d`). | 10 |
| Burn rate | How fast an error budget is being used, relative to the allowed pace. 1× spends it exactly over the period; 14.4× spends a 28-day budget in about 2 days (page); 6× in about 5 days (ticket). | 20 |
| C4 model | Architecture diagrams at four zoom levels: context (people and systems), containers (services), components, code. Kept here as code in `docs/architecture/workspace.dsl`. | 36 |
| Cache hit / miss | Hit: the answer was already stored and comes back in milliseconds. Miss: it had to be computed (the LLM ran) and is then stored. | 15 |
| Cache invalidation, epoch | Making old cached answers unusable when documents change; here, by bumping a counter (the epoch) that is part of every cache key, after every ingest or delete. | 33 |
| Cache key | The value a cache looks answers up by. It must include everything that changes the answer (prompt with retrieved context, model, parameters, user's permission scope, tenant), or answers leak between users. | 15 |
| Cache poisoning | A wrong, stale or someone-else's answer stored in a cache and then served to other requests, e.g. because the cache key left out the permission scope. | 15 |
| Canary release | Giving a new release a small share of traffic first (10%, 25%, 50%, then 100%), comparing it with the old one, and rolling it back by itself if it's worse. | 37 |
| Cap (deny overrides) | A limit that beats any grant: a contractor in `executives` still only reaches `internal`, because caps in `capped_groups` always win over group clearances. | 18 |
| Card status | Where a component is in its life: `planned → candidate → approved → deprecated → retired`; only approved or candidate models may be served. | 25 |
| Cardinality | How many distinct values a label has. User ids as metric labels create one time series per user: slow dashboards and big bills; keep labels to small fixed sets like `outcome` = ok or error. | 19 |
| Cask | A Homebrew package that is a normal Mac app with a window. | 1 |
| Catch rate | The share of known attacks a set of guards stops, redacts or flags. Only meaningful next to the false positive rate: a guard that blocks everything catches 100%. | 34 |
| CEL (Common Expression Language) | A small, safe expression language (no endless loops, no network calls) used by ValidatingAdmissionPolicies. | 29 |
| Change freeze | A period (e.g. year-end) in which no promotions happen; written in deploy/envs/promotion.yaml and checked by the gates. | 37 |
| Chat template | The model-specific recipe that turns a list of messages into the exact text format the model was trained on. | 7 |
| Chunk | A piece of a document that is embedded, retrieved and cited on its own; it carries a stable id, its text, what was embedded, its access rules and metadata. | 31 |
| Chunking strategy | The rule that decides where a document is cut into chunks: every N tokens, by paragraphs then sentences, along headings, by sentence, where the topic changes, or small children inside big parents. | 31 |
| CI (continuous integration) | Automatically checking every change (lint, types, tests, scans) on a fresh machine, so problems are found before they're merged. | 27 |
| Ciphertext | The scrambled, encrypted version of a value; unreadable without the right key. | 6 |
| Citation, attribution | Saying which source each claim came from (`[doc n]`), so a person can check it; checked here against the documents the model was actually shown. | 33 |
| Claim | One field in a token's payload, such as `iss`, `sub`, `groups` or `exp`. | 16 |
| Clearance | The highest classification (public < internal < confidential < restricted) a person may read, taken from their groups; no known group means no clearance at all. | 18 |
| CLI | Command-line interface: a program you control by typing commands. | 1 |
| ClickHouse | A fast column-oriented analytics database; Langfuse stores traces, observations and scores in it. | 22 |
| Client (OIDC) | An app registered with the identity provider. Public clients (browser, command line) can't keep a secret; confidential clients (servers, workers) can. | 16 |
| Client credentials | The flow where a machine signs in with its own client id and secret, with no person involved; it gets an access token but no refresh token. | 16 |
| Client scope | A reusable bundle of protocol mappers (and other token settings) that can be attached to many clients instead of repeating the mappers on each. | 16 |
| Clock skew / leeway | Small differences between machines' clocks; a tolerance (30 s here) stops a verifier from rejecting a token that is only just fresh or only just expired. | 17 |
| Cluster / node | A group of machines (nodes) Kubernetes runs containers on; OrbStack gives you a cluster of one node. | 29 |
| CODEOWNERS | A GitHub file naming who must review changes to which folders. | 4 |
| Collection (Qdrant) | Qdrant's equivalent of a table: a set of points sharing vector settings. | 12 |
| Collector (OpenTelemetry) | A service that receives, processes and exports telemetry; our single governance point that limits memory, scrubs secrets, redacts values, labels and batches (`otel-collector`). | 19 |
| Command category (Valkey) | A named group of commands used in ACLs, e.g. `@dangerous` (FLUSHALL, KEYS, CONFIG, DEBUG…) or `@admin`; `+@all -@dangerous` means everything except those. | 15 |
| Command Line Tools | Apple's free kit of basic developer programs: compiler, `make`, `git`, system headers. | 1 |
| Commit | A save point in git history, with a message explaining what changed and why. | 4 |
| Compiler | A program that turns human-written source code into a program the computer can run. | 1 |
| Component (rag-core) | One implementation of a contract, registered under a kind and a name, e.g. the `memory` vector store or the `gateway` LLM. | 30 |
| Compose project | The group of containers, networks and volumes one Compose file starts, sharing a name (`name: rag-platform`) that prefixes every container (`rag-platform-litellm-1`). | 9 |
| ConfigMap | A Kubernetes object holding non-secret configuration, e.g. the OpenBao Agent's config file. | 29 |
| Configuration as code | Keeping settings (which component fills each slot) in a reviewed, versioned file such as `rag.yaml`, checked by CI like code. | 30 |
| Conformance test | The same test suite run against every implementation of a contract (rag-core's conformance kit), so any one can replace another; its access checks fail with "LEAK". | 30 |
| Consumer group | A set of workers sharing one stream; each message goes to exactly one worker in the group, and the group remembers what was delivered and acknowledged. | 15 |
| Container (rag-core) | The object that reads a profile, builds each named component once, and hands components the others they need (dependency injection). Not a Docker container. | 30 |
| Container orchestration | Running containers across machines automatically: placing, restarting, scaling and updating them; what Kubernetes does. | 29 |
| Container | A running copy of an image: a self-contained "apartment" with a program and everything it needs. | 3 |
| Container runtime | The software that downloads images and runs containers (OrbStack, Docker Desktop, Colima, Podman). | 3 |
| Content addressing | Naming an object by a hash of its content (`sha256`), so identical files share a name and changes are detectable. | 14 |
| Content hash | A fingerprint (here SHA-256) computed from every byte of a file; any edit, even one character or a line ending, changes it. | 24 |
| Context compression | Keeping only the sentences of a chunk that matter for the question, so more sources fit in the budget. | 33 |
| Context packing | Choosing which retrieved chunks fit the token budget and in what order, and numbering them as `<doc id="n">` blocks. | 33 |
| Context propagation | Passing the trace id from one service to the next (in the `traceparent` HTTP header) so their spans join one trace. | 19 |
| Context recall | The share of the right documents that actually reached the model; what architectures change, and the first column of `rag eval-answers`. | 35 |
| Context window | The maximum number of tokens (prompt + answer) a model can handle at once. | 7 |
| Contextual retrieval | Having an LLM write one or two sentences placing each chunk in its document, and embedding them with the chunk (Anthropic, 2024); fewer failed retrievals for one LLM call per chunk. | 31 |
| Contract | The agreed list of methods a kind of component must have ("a vector store can upsert, delete, search with access rules, and count"); in rag-core, a Protocol. | 30 |
| Control (risk) | A measure that treats a threat, such as token checks, row-level security or an output guard; in the risk register each one names its evidence. | 36 |
| Control mapping | Showing which requirements of a framework (NIST AI RMF, ISO/IEC 42001, EU AI Act, APPs) each control helps meet. It shows contribution, not compliance. | 36 |
| Control plane | The parts of Kubernetes that decide (API server, etcd, scheduler, controllers), as opposed to the nodes that run the containers. | 29 |
| Controller / reconciliation | A loop that compares desired state with actual state and fixes the difference, forever; Kubernetes is made of them, and Argo CD is one too. | 29 |
| Conventional Commits | A commit-message format `type(scope)!: description` (e.g. `feat(gateway): …`) readable by people and tools. | 4 |
| Conversation memory | The earlier turns of a chat, kept per person and session (and forgotten after a TTL) so follow-up questions make sense. | 33 |
| Cooldown | Temporarily skipping a backend that keeps failing (LiteLLM: 30 s after 3 failures in a minute), so requests stop piling onto it. | 10 |
| Corrective RAG (CRAG) | Grading each retrieved chunk and using only relevant ones; searching differently, or abstaining, if none are. The `corrective` architecture. | 35 |
| CORS | Browser rules for which websites may call a server from inside a web page; too open (`*`) and any site you visit could call your local model. | 7 |
| Cosine similarity | A score for how closely two vectors point the same way: near 1 = very similar meaning, near 0 = unrelated. For unit-length vectors it equals the dot product. | 8 |
| Counter (metric) | A number that only goes up, such as requests served; dashboards turn it into a rate. | 19 |
| Cross-encoder | A model (the reranker) that reads the query and one document together and scores their relevance; precise but slow, so only used on a shortlist. | 8 |
| Crypto-shredding | Making data unreadable by destroying a key or a lookup instead of deleting it; reconciles "never delete" with the right to erasure (e.g. deleting the Keycloak account behind an audit `sub`). | 23 |
| CVE | Common Vulnerabilities and Exposures: a public ID for a known vulnerability (e.g. CVE-2021-44228, Log4Shell), which scanners like pip-audit and Trivy look up. | 27 |
| CycloneDX / SPDX | The two standard SBOM formats; Syft writes CycloneDX JSON here. SPDX also names the standard licence ids. | 27 |
| DAG (directed acyclic graph) | Arrows with no loops. Lineage must be one, or "what was this built from?" has no answer. | 25 |
| Dashboards as code | Generating dashboard definitions (Grafana JSON) from reviewed code in Git (`scripts/build_dashboards.py`) instead of clicking in the UI, with a check that fails when the committed JSON is out of date. | 20 |
| Data exfiltration (LLM) | Smuggling data out through the model, for example by getting it to put private text into a link or image URL that the user's browser then loads from an attacker's server. | 34 |
| Data filtering / partial evaluation (OPA) | OPA evaluating a policy with some facts still unknown and turning the rest into a filter, even a SQL `WHERE` clause, that a database can apply. | 18 |
| Data key | The random key SOPS creates per file to lock every value; it is itself locked once per recipient. | 6 |
| Data lifecycle | Everything that happens to data from creation to deletion: changes, access changes, copies, archiving, destruction. | 36 |
| Data retention | How long data is kept before it is deleted; for Langfuse traces, 30 days, enforced by our own nightly job because automatic retention is an Enterprise feature when self-hosted. | 22 |
| Database secrets engine | The OpenBao plug-in that creates a database user on request (CREATE ROLE … VALID UNTIL …) and drops it when the lease ends. | 28 |
| Dataset card / datasheet | A short document about a dataset: provenance, every location, personal data and legal basis, retention, deletion route, access, gaps. | 25 |
| DBSF (distribution-based score fusion) | A way to merge ranked lists by first scaling each list by its own spread (its mean plus or minus three standard deviations), so one extreme score doesn't squash the rest; the method Qdrant uses. | 32 |
| Dead-letter queue (DLQ) | Where jobs go after failing too many times (here: 3 deliveries), so they stop retrying forever and a human can inspect them. | 15 |
| Decision log | OPA's record of every decision (input, result, path, time, `decision_id`), written as JSON; the audit evidence for "who was allowed what, and why". | 18 |
| Decode | The second phase of generation: the model writes the answer one token at a time; its speed is limited by memory bandwidth. | 7 |
| Dedicated vector database | A database built only for storing vectors and finding the nearest ones fast, with filters (Qdrant, Milvus, Weaviate), rather than a general database with a vector extension. | 12 |
| `default` (Rego) | The value a rule takes when none of its bodies match, e.g. `default allow := false`; the building block of deny by default. | 18 |
| Deduplication | Dropping exact repeats (the same paragraph twice) so they don't crowd out everything else in search results. | 31 |
| Default privileges (ALTER DEFAULT PRIVILEGES) | A standing instruction that every table a given role creates from now on automatically gets certain grants, so new tables are never invisible to the app. | 11 |
| Defence in depth | Several independent layers of protection (identity, policy, ingestion redaction, store filters, citations, guards, audit), so one failing doesn't expose everything. | 34 |
| Delete marker | With versioning on, "delete" only adds a marker that hides the object; older versions still exist until each is deleted by version ID. | 14 |
| Delimiting | Wrapping untrusted text in clear markers (here XML-style tags like `<question>…</question>`) and telling the model that what's inside is data, not instructions. | 24 |
| Denied topic | A subject the assistant must not advise on (legal, medical, investment); questions about it get a fixed, helpful "contact the right team" message. | 34 |
| Dense retrieval | Search by meaning: the question and the chunks are turned into vectors and the closest vectors win. Finds "holiday" when the text says "annual leave"; misses exact codes like "E-4021". | 32 |
| Deny by default | Nothing is allowed unless a rule explicitly allows it; in Rego, `default allow := false`. | 18 |
| Dependabot | GitHub's bot that opens pull requests to update pinned versions (action SHAs, `uv.lock`, base images); CI tests each one before merging. | 27 |
| Dependency | A package your project needs in order to work. | 2 |
| Dependency group | A named set of extra dependencies in `pyproject.toml` (PEP 735), e.g. `dev` for test tools not needed in production. | 2 |
| Dependency injection | Giving a component the things it needs (an LLM, an embedder) from outside instead of it fetching them itself, so tests can hand it fakes. | 30 |
| Dependency injection (FastAPI) | FastAPI runs helper functions ("get the caller", "require this role") before an endpoint and passes their results in; tests swap them for fakes with `dependency_overrides`. | 17 |
| Deployment (LiteLLM) | One real backend behind a model alias; an alias can have several, for load-balancing or failover. | 9 |
| Deployment / ReplicaSet (Kubernetes) | "Keep N copies of this pod template running and change versions gradually"; the Deployment manages ReplicaSets, which manage Pods. | 29 |
| Derived index | A copy organised for fast lookup, always rebuildable from the source of truth. | 12 |
| Desired state | What you have written down should exist ("two copies of rag-api, this digest, these limits"); controllers make reality match it. | 29 |
| Deterministic check | A rule a program can check exactly, such as "cites document 2" or "contains no 'PWNED'": cheap, repeatable and explainable, so these form the evaluation gate. | 26 |
| Dev dependency | A package needed only while developing (e.g. pytest), not when the app runs in production. | 2 |
| Device flow | The sign-in flow for terminals and TVs: the app shows a link and a short code, you approve in a browser (with password and MFA), and the app receives tokens without ever seeing your password. | 16 |
| Digest (image) | `sha256:…` of an image's content. Unlike a tag, it can't later point at different content, so scanning, signing and deploying all use it. | 27 |
| Dimensions (of an embedding) | How many numbers an embedding vector has (Qwen3-Embedding-0.6B: up to 1,024); more can hold more nuance but costs storage and search time. | 8 |
| direnv | A tool that loads a project's settings automatically when you enter its folder. | 1 |
| Disaster recovery (DR) | Getting back after something high availability can't absorb: a region lost, or data destroyed by mistake; here a point-in-time restore into a new cluster, practised monthly. | 37 |
| Distance operator | pgvector's comparison symbols: `<=>` cosine distance, `<#>` negative inner product, `<->` Euclidean (L2), `<+>` L1. | 11 |
| Distributed lock | A short-lived "I'm working on this" marker shared by all workers (`SET key token NX PX 30000`): only one holder, expires on its own, released only with the owner's token. | 15 |
| Docker Compose | A file (`compose.yaml`) listing many containers and how they connect; `docker compose up` starts them all. | 3 |
| Docker engine / CLI | The engine runs containers inside the VM; the `docker` command is how you talk to it. | 3 |
| Downstream | Everything that depends on a component, directly or through others; what an impact analysis lists. | 25 |
| Drift | When the dependency list (`pyproject.toml`) and the lockfile (`uv.lock`) no longer match; `uv sync --locked` catches it. | 2 |
| Dual logging | Docker keeping a local copy of a container's recent output even when a remote logging driver (like `fluentd`) ships it elsewhere, so `docker compose logs` keeps working. | 21 |
| Dynamic secret | A secret created on request, for one client, with an expiry. It didn't exist before you asked, and it is gone after its lease ends. | 28 |
| EditorConfig | A small `.editorconfig` file telling every editor the same formatting basics (indentation, line endings). | 4 |
| Embedding / vector | A fixed-length list of numbers representing a text's meaning: a point in meaning space. | 8 |
| Embedding cache | A memory of "this text, with this model, gave this vector", so re-ingesting unchanged chunks or repeating a query costs nothing. | 31 |
| Embedding contract | Everything that defines how vectors were made (model + revision, dimensions, query instruction, normalisation, pooling, chunk limit); change any part and the index must be rebuilt. | 8 |
| Encryption | Scrambling data so only someone with the right key can unscramble it. | 6 |
| Endpoint | A specific URL path on a server, e.g. `/v1/chat/completions` or `/health`. | 7 |
| Enrichment (ingestion) | Adding context to what is embedded for a chunk (its title and section, an LLM-written context, the questions it answers) without changing the text that is shown and cited. | 31 |
| Entry point | A standard Python packaging hook: a package declares "my components live in this module" under `rag_core.components`, and rag-core loads them. | 30 |
| Envelope encryption | Values are locked with a random data key, and the data key is locked separately for each recipient, so adding a person never means re-encrypting every value by hand. | 6 |
| Environment parity | Staging is built from the same parts as production (same base, same production component), so "it worked in staging" means something. | 37 |
| Environment variable | A named value handed to a program when it starts (`DB_PASSWORD=…`); fine for settings, easy to leak for secrets. | 6 |
| Error budget | The amount of failure an SLO allows: with 99% of searches succeeding over 28 days, 1% may fail. Budget left: ship features; budget burning: prioritise reliability. | 20 |
| etcd | The key-value database where Kubernetes stores every object. | 29 |
| Evaluation (eval) | Running a system on test cases and scoring the results. | 26 |
| Eviction / maxmemory policy | What a memory-capped store deletes when it is full. `volatile-lru` removes the least-recently-used keys that have a TTL; `allkeys-lru` may remove any key, including queued jobs. | 15 |
| Evidence (compliance) | The proof that a control works: a file or a test that CI runs. The register names it as `path::test_name`, and the CI check fails if it disappears. | 36 |
| Exact / semantic cache | Reusing a stored answer for the same question (same normalised words) or for one with nearly the same meaning (embedding similarity); only among people who can see exactly the same documents. | 33 |
| Exemplar | A sample trace id attached to one metric data point, so a dot on a graph links straight to a real request's trace. | 21 |
| EXPLAIN | Asks Postgres how it will run a query, e.g. whether it uses an index; `EXPLAIN ANALYZE` also runs it and shows real timings. | 11 |
| Explain API | Adding `"explain": true` to a search so OpenSearch returns the arithmetic behind each score (tf, idf, length adjustment). | 13 |
| Exporter (Prometheus) | A small adapter that reads a system's own statistics and serves them as `/metrics` for Prometheus, e.g. `postgres_exporter` for rag-db, logged in as the read-only `rag_metrics` role. | 20 |
| Extension (Postgres) | An add-on that teaches Postgres new tricks; `vector` (pgvector) adds vector types and indexes. | 11 |
| Fail closed | When unsure, deny: no groups in the token means no documents, not all documents; an unreachable key service means 503, not "let it through". | 17 |
| Fail open | The opposite of fail closed: when something breaks or a fact is missing, let the request through. Never acceptable for security; an undefined Rego value can cause it silently. | 18 |
| Fail open (search helpers) | For helpers that only improve results (a reranker, a query rewriter): when one fails, continue without it and record that, instead of failing the whole search. Never used for access checks, which always fail closed. | 32 |
| Fail open / fail closed (guards) | What a guard does when its service or model can't be reached: flag and let the other guards decide (open, the default here) or block (closed). A per-project policy choice. | 34 |
| Failover | Switching to a standby automatically when the active part fails, e.g. CloudNativePG promoting a replica to primary. | 37 |
| Faithfulness | Every claim in an answer is supported by the documents it was given (nothing invented). | 26 |
| Fallback | Sending a request to a different model when the first one fails; fine between chat models, never between embedders (different vector spaces). | 10 |
| False positive | A check flags something that is actually fine; silence it narrowly, with a comment explaining why. | 5 |
| False positive (guards) | An ordinary request wrongly stopped by a guard; measured as the false positive rate by `rag eval-guards` and gated in CI as closely as the catch rate. | 34 |
| FinOps | The practice of making technology spend visible, attributed to teams, and managed against budgets; AI FinOps applies it to model usage. | 10 |
| `for` (alert duration) | How long an alert's condition must stay true before it fires (`for: 2m`). Stops a single wobbly reading from paging anyone. | 20 |
| Formatter | A tool (e.g. `ruff format`) that rewrites code layout into one consistent style without changing what it does. | 5 |
| Formula | A Homebrew package that is a command-line tool. | 1 |
| Full-text search / tsvector | Postgres's built-in keyword search: words normalised to stems (a `tsvector`) and indexed with GIN. | 11 |
| Fusion (rank fusion) | Merging several ranked lists (from vector search, keyword search, or several search texts) into one list, without adding raw scores of different kinds. | 32 |
| Gate (quality gate) | Pass/fail rules a run must meet before a change ships: thresholds in `evals/gates.yaml`, the prompt's own `min_score`, and no regression against the baseline. | 26 |
| Gateway (AI / LLM gateway) | A server in front of all model servers: every request passes through it for authentication, allow-listing, routing, limits and logging. | 9 |
| GenAI semantic conventions | The emerging standard `gen_ai.*` attribute names for model calls (operation, model, token usage), so LLM tools and vendor dashboards understand each other. | 19 |
| Generation (LLM observability) | An observation for one LLM call: prompt, completion, model, tokens and cost (recorded from Step 33). | 22 |
| Genesis (hash chain) | The starting point of a hash chain: here 32 zero bytes, used as the "previous hash" of row 1. | 23 |
| GIN index | A Postgres "inverted" index for values with many parts: arrays, JSON and words. | 11 |
| Git hook | A script git runs automatically at a set moment: before a commit, after the message is written, before a push. | 5 |
| .gitattributes | Rules for how git treats file types (line endings, binary files, generated files). | 4 |
| `GITHUB_TOKEN` / permissions | The short-lived token every GitHub Actions job gets automatically; the workflow's `permissions:` block limits what it may do (read-only by default here). | 27 |
| .gitignore | A "do not pack" list of files git must never track (secrets, `.venv`, data, models). | 4 |
| GitOps | Git holds the declarative desired state; an agent in the cluster pulls it and continuously reconciles the cluster to it (OpenGitOps principles). | 29 |
| Golden dataset | Test cases with known good answers (or expected documents), written and checked by people, versioned and pinned by hash. | 26 |
| Graceful degradation | Continuing with reduced quality or features instead of failing completely, e.g. skipping reranking and flagging the answer when the reranker is down. | 10 |
| Grant / flow | A standard recipe for getting a token: authorization code + PKCE (web apps), device flow (CLIs), client credentials (machines). The password grant (ROPC) is switched off. | 16 |
| GraphRAG (local and global search) | Using a knowledge graph to find related information: local search follows the entities near the question (built in here as `graph`); global search summarises whole communities of entities to answer "what are the main themes?". | 35 |
| Groundedness | Whether each claim in an answer is supported by the sources the model was given; checked here lexically (content words and exact numbers must appear in the sources). | 34 |
| Group (Keycloak) | A set of users who are "with" each other (department, team). It decides what you may SEE: its name goes into the token's `groups` claim and matches documents' `acl_groups`. | 16 |
| Grouping (alerts) | Alertmanager combining related alerts (same `alertname` and `service` here) into one notification instead of one per time series. | 20 |
| Guardrail (guard) | A check before or after the model (on the question, the retrieved documents or the answer) that can allow, flag, redact or block. | 34 |
| halfvec | A pgvector type that stores each number in 2 bytes instead of 4: half the storage, negligible quality loss for embeddings. | 11 |
| Hallucination | A fluent, confident answer that isn't supported by the sources (or by reality). | 33 |
| Hash | A short fingerprint calculated from a file's contents; change one byte and it changes completely. | 2 |
| Hash chain | Records linked by including each previous record's hash in the next one's hash, so editing any record breaks every later link. | 23 |
| Head (hash chain) | The newest hash of a chain; it summarises the entire chain up to that point. | 23 |
| Headless initialisation | Creating an application's organisation, project, API keys and first admin from configuration at first start, with no clicking (Langfuse's `LANGFUSE_INIT_*` variables). | 22 |
| Healthcheck | A command Compose runs inside a container every few seconds to ask "are you working?"; failures mark it unhealthy. | 9 |
| Helm (chart, values, release) | Kubernetes' package format: templated manifests (a chart) filled in from values; an installed instance is a release. | 29 |
| High availability (HA) | Staying up when a part fails: several replicas spread over zones, so losing one machine or zone isn't an outage. | 37 |
| Histogram (metric) | A metric that records a distribution of values (e.g. latencies), from which p50/p95/p99 are computed. | 19 |
| `histogram_quantile` | The PromQL function that estimates a percentile (e.g. p95) from histogram buckets; it can only be as precise as the bucket edges allow. | 20 |
| HMAC (keyed hash) | A one-way fingerprint of a value made with a secret key. OpenBao's audit log stores HMACs instead of secret values; `sys/audit-hash` computes one so you can search the log for a value you hold. | 28 |
| HNSW | Hierarchical Navigable Small World: a layered graph index for fast approximate vector search, tuned by `m`, `ef_construction` and `hnsw.ef_search`. | 11 |
| Homebrew | The standard package manager ("app store for developer tools") on macOS. | 1 |
| host.docker.internal | The address a container uses to reach programs running on the host Mac itself. | 3 |
| Hybrid search | Running keyword (BM25) and vector search together and fusing their normalised scores; robust across exact-code and paraphrase questions. | 13 |
| HyDE (Hypothetical Document Embeddings) | Let an LLM write a plausible answer to the question, then search with that passage (embedded like a document), because answers look more like answers than questions do. | 32 |
| Hypothetical questions | Questions an LLM says a chunk answers, embedded with it so that how users ask and how documents state meet in the same place. | 31 |
| ID token | The token that tells the app (not the API) who signed in: name, username, email. | 16 |
| Idempotency | Doing a job twice has the same effect as doing it once ("upsert chunks for document X at hash Y", not "append chunks"). Required with at-least-once delivery. | 15 |
| Idempotent upsert | Writing the same chunk twice leaves one copy, because chunk ids are stable (same document, position and text = same id). | 31 |
| Identity provider (IdP) | The service that signs people and machines in and vouches for them with signed tokens; Keycloak in this platform. | 16 |
| Image | The frozen blueprint a container is started from: a program plus all its dependencies. | 3 |
| Image tag vs digest | A tag (`v1.104.0`) is a movable label; a digest (`@sha256:…`) is the exact, unchangeable fingerprint of one image. | 9 |
| Immutability (prompt versions) | A released prompt version can never change; a change means a new version, so `name@version` always means the same text. | 24 |
| Impact analysis | Following lineage downstream to find everything affected by a change, and who owns it (`just cards impact`). | 25 |
| Info metric | A metric whose value is always 1 and whose labels carry facts, e.g. `rag_prompt_info{prompt, version, sha, label}`; a Prometheus convention for "what is running". | 24 |
| Ingestion | Everything between "here is a file" and "its pieces can be searched": parse, clean, redact, chunk, enrich, embed, index. | 31 |
| Inhibition | An Alertmanager rule that mutes some alerts while another fires: here a critical alert mutes its warning twin with the same `alertname` and `service`. | 20 |
| In-memory key-value store | A database that keeps data in RAM and retrieves it by a key (a name). Extremely fast, but limited by memory; Valkey and Redis are examples. | 15 |
| Infrastructure as code | Defining your environment in version-controlled files instead of setting it up by hand. | 1 |
| `input` vs `data` (Rego) | `input` holds the facts about this one request (who, which action, which documents); `data` holds standing facts loaded with the policy, such as `data.json` mappings. | 18 |
| Instrumentation (automatic vs manual) | Code that creates telemetry: libraries that make spans for you (HTTP, SQL) versus spans you add for your own logic (retrieval, policy decisions). | 19 |
| Internal user | A user stored inside OpenSearch's own security index (here `rag_search`, `rag_indexer`). | 13 |
| Interpreter | The `python` program itself: the engine that reads and runs Python code, e.g. CPython 3.12. | 2 |
| Inverse document frequency (idf) | How rare a word is across all documents; rare words count for much more in BM25. | 13 |
| Inverted index | A map from each word to the documents containing it, like the index at the back of a book. | 13 |
| Issuer (`iss`) | The claim naming who made a token (`http://localhost:8180/realms/rag`); APIs only accept tokens from the issuer they trust. | 16 |
| Iterative scan | pgvector 0.8+ setting (`hnsw.iterative_scan`) that keeps scanning the index until enough rows pass the filters, avoiding silently short results. | 11 |
| IVFFlat | An older pgvector index that groups vectors into lists (clusters) and searches only the nearest lists; faster to build, usually lower recall than HNSW. | 11 |
| Jailbreak | A prompt designed to get a model past its safety rules ("you are now DAN…", "developer mode"). | 34 |
| justfile | A menu of named command shortcuts run with `just <recipe>` (e.g. `just check`), reused by CI. | 4 |
| JVM heap | The working memory of a Java program such as OpenSearch; typically about half the container's memory, fixed and locked in RAM. | 13 |
| JWKS (JSON Web Key Set) | The public keys an identity provider publishes (`…/protocol/openid-connect/certs`) so anyone can check its token signatures. | 16 |
| JWKS cache | The verifier's local copy of the identity provider's public keys (5 minutes here), re-fetched when a token names an unknown `kid`; avoids a Keycloak call per request. | 17 |
| JWT (JSON Web Token) | A small signed token carrying its own permissions and expiry; anyone can read it, but only the holder of the signing key can create or change it. | 12 |
| k-NN plugin / Lucene engine | OpenSearch's vector search feature, here using Lucene's HNSW implementation. | 13 |
| Key pair (public / private key) | Two matching keys: anyone can lock with the public key, only the private key unlocks. Share the public one, guard the private one. | 6 |
| Key rotation | The identity provider switching to a new signing key; APIs must pick up the new key automatically (a JWKS re-fetch on an unknown `kid`) while old tokens expire. | 17 |
| Keyless signing | Signing with a minutes-long certificate tied to the CI job's identity (via OIDC and Sigstore) instead of a long-lived private key, so there's no key to steal or rotate. | 27 |
| `kid` (key id) | A label in a JWT's header naming which of the identity provider's keys signed it, so the verifier knows which public key to check with. | 17 |
| Knowledge graph, entity | A map of named things (systems, policies, error codes, teams) and how they are connected; each named thing is an entity. | 35 |
| kubelet | The agent on each node that starts containers, runs probes and writes service account tokens into pods. | 29 |
| Kustomize (base, overlay, component) | Plain Kubernetes YAML plus declared changes: a base, per-environment overlays, and reusable components; built into `kubectl`. | 29 |
| KV cache | The model's working memory of everything read so far; grows with prompt and answer length and is a big part of memory use. | 7 |
| KV v2 | OpenBao's key/value secrets engine, version 2: stores fixed secrets (here the gateway key and OPA token) with a version history. Data lives under `secret/data/…`, versions under `secret/metadata/…`. | 28 |
| Label (metric) | A key=value pair that identifies one slice of a metric, e.g. `outcome="error"`, `job="opa"`, `service_version="0.1.0"`. Every distinct label combination is its own time series. | 20 |
| Label (prompt) | A movable pointer from an environment to a prompt version ("production uses version 1, staging uses version 2"), kept in `prompts/labels.yaml`. | 24 |
| launchd | macOS's built-in service manager: starts programs at login and restarts them if they crash (agents live in `~/Library/LaunchAgents/`). | 7 |
| Layout analysis | Working out a page's reading order, columns, tables and figures (Docling does this; plain text extraction doesn't). | 31 |
| Lease | The ID and time to live that come with every dynamic secret. It can be renewed up to the max TTL or revoked early; when it ends, the secret is destroyed (for a database login: sessions ended, user dropped). | 28 |
| Least privilege | Giving each identity only the access it needs and nothing more. | 10 |
| Legal basis (GDPR) | The reason that makes processing personal data lawful (contract, legal obligation, legitimate interest…); required on every dataset card with personal data. | 25 |
| Legal hold | An indefinite object lock with no date, applied during investigations, until someone explicitly removes it. | 14 |
| Legal hold (retention) | An instruction to keep matching records whatever the retention rules say while a matter is open; in `legal_holds:` of the retention file, it beats `rag retention` and makes `rag erase-source` need a recorded override. | 37 |
| Lifecycle rule | An automatic action on objects by age, e.g. "delete temp files after 1 day" or "expire old versions after 90 days". | 14 |
| LimitRange | Per-container defaults and maximums for a namespace (here: 256 MiB default memory limit, 2 GiB max). | 29 |
| Line filter (LogQL) | A LogQL step that keeps only lines containing (`|=`), not containing (`!=`) or matching (`|~`) some text, e.g. `|= "4bf92f35…"` to find one request's lines. | 21 |
| Lineage | The recorded chain from an output (an answer) back to its inputs (chunks → document → exact file version). | 14 |
| Linter / static analysis | A tool (e.g. `ruff check`) that reads code without running it and flags likely bugs and risky patterns, each as a coded rule like `B006`. | 5 |
| Listwise reranking | Reranking where an LLM sees all candidate passages at once and returns their order ("3 > 1 > 2"); strong on reasoning-heavy questions, slow and costly. | 32 |
| Liveness / readiness | Two health questions: "is the process alive?" (restart it if not) and "can it serve traffic yet?". | 9 |
| LLM observability | Recording what an AI system was asked, what it looked up and what it answered, to debug and improve it (Langfuse here). | 22 |
| LLM-as-judge | A model grading another model's answer against a reference. Useful, but biased (prefers longer answers and its own style) and fallible, so here it only advises. | 26 |
| localhost / 127.0.0.1 | "This machine only": a port bound here is reachable only from your own Mac. | 3 |
| Lock file (prompts) | `prompts/prompts.lock.json`: the SHA-256 of every released prompt version; entries may be added, never changed or removed. | 24 |
| Lockfile | A file recording the exact version and hash of every package in the full dependency tree (`uv.lock`). | 2 |
| Log aggregation | Collecting every container's log lines into one central, searchable store with retention (Loki here) instead of reading files on each machine. | 21 |
| Log rotation | Keeping only the newest few log files of a limited size and deleting the oldest (here 3 × 10 MB). | 3 |
| Logging driver (Docker) | Where the Docker engine sends a container's stdout/stderr: `json-file` (default, local disk) or a network destination such as `fluentd`, which the Collector's `fluent_forward` receiver understands. | 21 |
| Login events (Keycloak) | Keycloak's record of sign-ins and failures (`LOGIN`, `LOGIN_ERROR`, …) with time, IP address and client; kept 30 days here. | 16 |
| LogQL | Loki's query language: pick streams by label (`{service_name="rag-api"}`), then filter lines (`|= "text"`) and parse them (`| json`). | 21 |
| Log–trace correlation | Putting the trace and span id in every log line, so you can jump from a trace to the exact log lines of that request and back. | 19 |
| Loki | Grafana's log store: indexes only a few labels per stream and keeps the text in compressed chunks that are scanned at query time, so it is cheap to run. | 21 |
| Lost in the middle | Models notice the start and end of a long context more than the middle; the `lost-in-middle` order puts the best chunks at both ends. | 33 |
| macOS Keychain | The Mac's built-in encrypted password store, unlocked by your login; home for personal tokens. | 6 |
| maintenance_work_mem | Postgres memory for maintenance work such as building indexes; HNSW builds are much faster when the graph fits in it. | 11 |
| Manifest (audit archive) | A small file describing one archived batch of audit events: first and last row, head hash, previous head and the segment's checksum. | 23 |
| Manifest (ingestion) | The record of each ingested source: its content hash, the pipeline hash, how many chunks, the status and when; unchanged sources are skipped. | 31 |
| Mapping | An OpenSearch index's schema: each field's type (`text`, `keyword`, `knn_vector` …) and analyzer. | 13 |
| Masking hook | A function in our own process that rewrites every value (tokens, keys, emails → `****`) before it is sent to Langfuse. | 22 |
| Master key | The gateway's root credential (`LITELLM_MASTER_KEY`); it can do everything, so it is for admins only. | 9 |
| Matryoshka embeddings | Embeddings trained so their first part is already a useful smaller embedding; keep the first N numbers, re-normalise, and save storage at a small quality cost. | 8 |
| Max parallel requests (concurrency limit) | How many requests one key may have in flight at once; crucial when every app shares one GPU. | 10 |
| MDM | Mobile Device Management: how company IT installs and controls software on employees' Macs (e.g. Jamf, Kandji). | 1 |
| Meaning space | The many-dimensional map an embedding model places texts on, where similar meanings sit close together. | 8 |
| Memory bandwidth | How fast data moves between memory and the GPU; each decoded token reads the model's weights, so it is the speed limit for tokens per second. | 7 |
| Merkle tree | A tree of hashes in which each parent hashes its children; allows small proofs that an entry is included in a large log. | 23 |
| Mermaid | A text format for diagrams that GitHub and many wikis render automatically; `docs/cards/README.md` draws the lineage with it. | 25 |
| Metric | A number measured over time (requests per second, latency, errors); answers "is something wrong?". | 19 |
| MFA / TOTP | Multi-factor authentication: a second proof besides the password. TOTP is the six-digit, time-based code from an authenticator app. | 16 |
| Migration | A versioned, reviewable script that changes the database structure, applied in order and recorded in the database. | 11 |
| Min-max normalisation | Stretching a list of scores so the lowest becomes 0 and the highest 1, so scores of different kinds can be weighted and added; sensitive to outliers. | 32 |
| Mixture of Experts (MoE) | A model that stores many specialist sub-networks but uses only a few per token: memory like a big model, speed like a small one. | 7 |
| ML-BOM | A machine-readable bill of materials listing models and datasets (CycloneDX ML-BOM, SPDX 3 AI/Dataset profiles). | 25 |
| MMR (Maximal Marginal Relevance) | Choosing results one by one, each time the candidate that is relevant AND least like those already chosen: fewer near-repeats in the context. | 32 |
| Model alias (model group) | The public role name clients use, such as `qwen-fast`; LiteLLM calls it `model_name`. | 9 |
| Model card | A short document about one model: what it is, where it came from, intended use and out-of-scope use, limits, risks, evaluation, licence. | 25 |
| Model inventory | A reviewed list of which exact models a platform serves: repo, revision, licence, port, role and who approved it (`infra/model-serving/models.yaml`). | 7 |
| Model revision | The exact git commit (40-character SHA) of a model repository on Hugging Face; the same name isn't always the same model. | 7 |
| Monorepo | One repository holding all services, libraries, infrastructure and docs. | 4 |
| MRR (mean reciprocal rank) | On average over queries, 1 / position of the first relevant result: 1.0 means the right document always comes first. | 26 |
| Multi-hop question | A question that needs two or more facts found in different places, in sequence ("which systems did the 2024 incident touch, and who owns them?"). | 35 |
| Multi-query | An LLM writes several paraphrases of the question; each is searched and the lists are fused. Better recall for questions worded unlike the documents, at the cost of more searches. | 32 |
| Multi-stage build | A Dockerfile with several `FROM` stages: one with build tools makes the result, the final small image copies only that result (here the finished `.venv`). | 17 |
| Multitenancy / tenant | Serving many customers or departments from one system / one such customer, whose data must stay separate. | 12 |
| Multi-window alert | A burn-rate alert that requires both a long window (1 h or 6 h: a real trend) and a short one (5 min or 30 min: still happening) to be over the threshold, so blips don't page and alerts clear quickly after recovery. | 20 |
| Naive RAG | Embed the question, take the top k most similar chunks, answer: the textbook baseline that other designs are measured against. | 35 |
| Named vectors | Several vectors stored per point under different names, e.g. `dense` and `sparse`. | 12 |
| Named volume | Docker-managed storage inside the VM that survives container deletion; use it for database data. | 3 |
| Namespace (Kubernetes) | A folder for objects, with its own rules, quotas and permissions. | 29 |
| Native sidecar | An init container with `restartPolicy: Always` (Kubernetes 1.33+): starts first, keeps running beside the app. | 29 |
| nDCG (normalised discounted cumulative gain) | A score from 0 to 1 that rewards relevant documents near the top of a ranked list; 1.0 is the perfect order. | 26 |
| Network interface | A way your machine connects to networks: Wi-Fi, Ethernet, or localhost. | 3 |
| NetworkPolicy | A firewall rule between pods, enforced only if the cluster's network plugin supports it (`just k8s-netpol-check`). | 29 |
| no-new-privileges | A container security option that stops any process inside it gaining extra privileges, e.g. through setuid programs. | 9 |
| --no-verify | A git flag that skips local hooks; the reason CI must repeat the same checks. | 5 |
| Non-root container | A container whose process runs as an ordinary user (uid 10001 here), so a compromised app can't change system files or its own code. | 17 |
| Normalisation | Scaling a vector to length 1, so cosine similarity becomes a simple dot product. | 8 |
| Normalisation (text) | Making text uniform before chunking: ligatures and full-width characters folded (NFKC), control characters removed, hyphenated line breaks re-joined, whitespace collapsed. | 31 |
| OAuth 2.0 / OpenID Connect (OIDC) | The standards for getting tokens. OAuth 2.0 covers access ("may this app call that API?"); OIDC adds identity (who signed in) on top. | 16 |
| Object lock / retention (governance vs compliance) | Rules preventing deletion or overwrite of an object version until a retain-until date (WORM). Governance mode: privileged users can deliberately override; compliance mode: nobody can, not even admins. | 14 |
| Object metadata | Extra key-value information stored with an object (content type, source URI, sha256…). | 14 |
| Object storage / S3 API | Storing files as objects in buckets, reached over HTTP using Amazon's S3 protocol, now an industry standard spoken by AWS S3, SeaweedFS, Ceph and many more. | 14 |
| Observability | Being able to answer new questions about a running system from the outside, using its traces, metrics and logs, without shipping new code. | 19 |
| Observation (Langfuse) | One step inside a Langfuse trace, with a type: `chain`, `retriever`, `embedding`, `generation`, `tool`, `agent` … | 22 |
| OCR (optical character recognition) | Reading text out of an image, such as a scanned page that has no text layer. | 31 |
| OIDC token (CI) | A signed statement from GitHub saying "this job is repo X, workflow Y, branch Z"; Sigstore's Fulcio trusts it to issue a signing certificate. | 27 |
| Online evaluation | Measuring answer quality from real use (outcomes, citations, guard flags, thumbs up/down) per release, rather than from labelled test questions. | 37 |
| Opaque token | A token that is just a random reference, not a readable JWT; only the identity provider can say what it means, via introspection. | 17 |
| Open core | A free (here MIT-licensed) core product plus paid Enterprise features; Langfuse's model. | 22 |
| OpenAI-compatible API | The same request and response format as OpenAI's API, so any tool that speaks "OpenAI" can call a local model. | 7 |
| OpenBao | The open-source (MPL-2.0) fork of HashiCorp Vault, run under the Linux Foundation; same API, policies and concepts, binary called `bao`. Our secrets manager. | 28 |
| OpenBao Agent | A helper process next to an application (here the rag-api-agent sidecar): logs in (auto-auth), renews, and writes secrets into files (templates) so the application never talks to OpenBao. | 28 |
| OpenFGA | A CNCF relationship-based (ReBAC) authorisation engine modelled on Google's Zanzibar: "shared with", folder inheritance, team membership. Planned for the permission-aware RAG project. | 18 |
| OpenLineage | An open standard for lineage events emitted by pipelines ("job X read A, wrote B"); Marquez is its reference server. Lineage observed, not declared. | 25 |
| OpenSSF Scorecard | An automated score of a repository's security practices (pinning, branch protection, reviews…); a quick external check for public repositories. | 27 |
| OpenTelemetry | The CNCF open standard (APIs, SDKs, protocol, Collector) for producing and shipping traces, metrics and logs, supported by every major vendor. | 19 |
| OrbStack | A lightweight macOS container runtime: Linux VM + Docker engine + Compose + single-node Kubernetes. | 3 |
| OTLP | The OpenTelemetry protocol that carries all three signals: gRPC on port 4317, HTTP on 4318. | 19 |
| Overlap (chunking) | Repeating the end of one chunk at the start of the next, so a thought cut at the boundary appears whole in one of them. | 31 |
| Overlay (Kustomize) | One small file per environment that layers names, sizes and settings on top of a shared base (and reusable components). | 37 |
| Override (configuration) | Changing one setting for one deployment without editing the file, e.g. `RAG__RERANKER__TOP_N=5`; double underscores mean nesting, values are YAML. | 30 |
| Package manager | A program that installs, updates and removes other software and tracks what's installed. | 1 |
| PAP (Policy Administration Point) | Where the rules are written and changed; here Git and pull requests on `policies/`. | 18 |
| Parent / child span | Spans nest: a request's server span is the parent of the steps inside it, which can have children of their own; this nesting draws the waterfall. | 19 |
| Parent-child chunking (small-to-big) | Searching small child chunks for precision, then giving the model the larger parent section they belong to. | 31 |
| Parser (LogQL) | A LogQL step such as `| json` or `| logfmt` that turns each line's text into fields you can filter on, e.g. `| json | level="ERROR"`. | 21 |
| Parsing | Turning a file's bytes into text with structure: which part is a heading, a list, a table, page 3. | 31 |
| Password grant (ROPC) | The "resource owner password credentials" grant, where an app collects your password and swaps it for tokens. Modern OAuth guidance says never: the app sees the password and MFA can't work. | 16 |
| PATH | The ordered list of folders your shell searches when you type a command. First match wins. | 1 |
| Path-style addressing | Putting the bucket name in the URL path (`http://host:8333/bucket/key`) instead of the host name; common for self-hosted S3 stores. | 14 |
| Payload | The JSON metadata stored with a Qdrant point (tenant, access groups, title, text…). | 12 |
| Payload index | An index on a payload field so filters on it are fast. Without one, filtering scans. | 12 |
| PDP (Policy Decision Point) | The component that decides; here OPA, answering from the policy and its data. | 18 |
| Pending entry | A stream message delivered to a consumer but not yet acknowledged; if the consumer crashed, another worker can reclaim it (`XAUTOCLAIM`). | 15 |
| PEP | Python Enhancement Proposal: an official Python standard (e.g. PEP 621 `pyproject.toml`, PEP 735 dependency groups, PEP 668 protected system Pythons). | 2 |
| PEP (Policy Enforcement Point) | The component that asks for a decision and obeys it, never deciding itself; here rag-api. (Not to be confused with a Python Enhancement Proposal.) | 18 |
| Persistence: RDB / AOF | How an in-memory store survives restarts. RDB: periodic snapshots to disk. AOF (append-only file): a log of every write, replayed at start-up; `appendfsync everysec` loses at most about 1 s. | 15 |
| Persona (evaluation) | A synthetic person (name, groups) an evaluation runs as, so the real access rules apply; never a real person's account. | 26 |
| pg_dump | Postgres's logical backup tool: writes a database's structure and data to a file that `pg_restore` can load again. | 11 |
| PII (personally identifiable information) | Information about a person (email, phone, card, tax file number, IP address…); redacted at ingestion so no index, cache or log keeps it. | 31 |
| Pinning by SHA | Referring to an exact commit (`@3d3c42e…`) or file hash instead of a tag (`@v7`): tags can be moved to other code, commits and hashes can't. | 27 |
| Pipeline (Collector) | One signal's path through the Collector: receivers → processors (in order) → exporters. | 19 |
| Pipeline hash | A fingerprint of the settings that shape the index (parsers, cleaning, PII, chunker, enrichers, embedder); when it changes, every source is re-ingested. | 31 |
| Placeholder | A slot like `{{question}}` in a prompt template that is filled in for each request; every one must be declared in `variables`. | 24 |
| Plaintext | Readable, unencrypted text. | 6 |
| Plugin | A component that lives in another package and is discovered at run time, so adding it needs no change to rag-core. | 30 |
| Pod Security Standards | Kubernetes' built-in profiles (privileged, baseline, restricted), enforced per namespace by a label. | 29 |
| Pod | One or more containers that run together and share network and volumes; the unit Kubernetes schedules. | 29 |
| PodDisruptionBudget | "Never voluntarily take away more than this many pods", e.g. during node maintenance. | 29 |
| Point | One item stored in Qdrant: an ID, one or more vectors, and a payload. Here, one chunk. | 12 |
| Point-in-time recovery (PITR) | Restoring a database to any second inside a window (30 days here) from a base backup plus the archived write-ahead log. | 37 |
| Policy (OpenBao) | A list of paths and what a token may do with them (read, create, update, delete, list, sudo). Anything not listed is denied. | 28 |
| Policy as code | Access rules written in a real language, versioned in Git, reviewed by pull request and tested like code. | 18 |
| Policy engine | A service whose only job is to evaluate authorisation rules against facts and answer yes/no plus details; here OPA. | 18 |
| Polyrepo | One repository per service or library. | 4 |
| Pooling | How an embedding model squeezes its per-token outputs into one vector (Qwen3-Embedding uses the last token). | 8 |
| Port | A numbered "door" through which a program accepts network connections, e.g. 5432 for Postgres. | 3 |
| pre-commit (the tool) | A framework that installs and runs git hooks from one file, `.pre-commit-config.yaml`. | 5 |
| Pre-filter vs post-filter | Restricting a search inside the query (pre-filter, using the filter the policy computed) vs checking the results afterwards (post-filter); we do both, so leaks are impossible and results stay full. | 18 |
| precision@k | The share of the top k results that is relevant. "How much noise reaches the prompt?" | 26 |
| Prefill | The first phase of generation: the model reads every prompt token in one parallel pass; limited by compute, it sets TTFT. | 7 |
| Presigned URL | A link with a built-in signature and expiry that grants temporary access to one object (or one version) without the opener needing credentials. | 14 |
| Primary key / foreign key | A row's unique ID / a column pointing to another table's row (a chunk → its document). | 11 |
| Principal | The verified caller as the code sees it after token validation: user id (`sub`), username, calling app (`azp`), groups and roles. | 17 |
| Probe (startup, readiness, liveness) | Checks the kubelet runs on a container: has it started, should it get traffic, should it be restarted. | 29 |
| Production readiness | Whether a configuration should run in production, not just whether it can: no in-memory stores or stand-in models, required guards, no secrets in the file (`rag config readiness`). | 37 |
| Profile (rag.yaml) | A named set of component choices (`offline`, `local`, …); `extends` copies another profile and changes some parts. | 30 |
| Progressive delivery | Releasing a change gradually with automatic checks at each step (canaries, analysis), instead of to everyone at once. | 37 |
| Project and API keys (Langfuse) | A Langfuse project holds traces; its public key (`pk-lf-…`) identifies it and its secret key (`sk-lf-…`) authorises writes. | 22 |
| Projected service account token | A short-lived token the kubelet writes into a pod for one audience only (here `openbao`, 10 minutes) and refreshes automatically. | 29 |
| Promotion (deployment) | Moving a tested, signed build to an environment; here a one-line digest change by pull request (`just promote`). | 29 |
| Promotion / rollback | Moving a prompt label to a newer version / back to an older one: a one-number change in `labels.yaml`, reviewed as a pull request. | 24 |
| Prompt | The text given to a model: instructions plus the material to work on. | 24 |
| Prompt cache | Reusing the KV cache of a prompt start sent before (e.g. the same system prompt), which makes TTFT much faster. | 7 |
| Prompt injection (as a test) | An evaluation case that deliberately attacks the prompt, through a hostile document or question, and passes only if the answer ignores the attack (e.g. never says "PWNED"). | 26 |
| Prompt injection (direct, indirect) | Text that tries to make the model follow its instructions instead of yours. Direct: typed by the user. Indirect: hidden in a retrieved document or web page. | 24 |
| Prompt leaking | Getting the model to reveal its system prompt or hidden instructions ("print your system prompt"). | 34 |
| Prompt registry | One place where all prompts live, with versions, owners, history and labels; here the `prompts/` folder plus `rag_common.prompts`. | 24 |
| Prompt template | A prompt with placeholders that get filled in for each request. | 24 |
| Prompts as code | Keeping prompts as files in git, so they get reviews, history and CI like code. | 24 |
| PromQL | Prometheus's query language: select series by name and labels, then compute with functions like `rate()`, `increase()`, `sum by (…)` and `histogram_quantile`. | 20 |
| Protocol (structural typing) | A Python type that describes a shape (methods and attributes); any class with that shape fits, no base class needed. `runtime_checkable` lets `isinstance` check it too. | 30 |
| Protocol mapper | A Keycloak rule that puts an extra fact into tokens, such as the `groups` claim or an extra audience. | 16 |
| Provenance | Where something came from, and how it was made. | 25 |
| Provenance (evaluation run) | The record of exactly what an evaluation measured: dataset version and SHA-256, target, prompt and model, judge, git commit and time. | 26 |
| Provider prefix | The part of a LiteLLM `model` before the first `/` (e.g. `openai/`): which API protocol to speak to the backend. | 9 |
| Provisioning (Grafana) | Grafana reading its data sources and dashboards from files at start-up, so they are code in Git rather than settings clicked into its database. | 20 |
| Pseudonymisation | Replacing personal data with a keyed token (an HMAC): the same value always gives the same token, so joins and counts still work, but nobody without the key can reverse it. | 31 |
| Pseudonymous id | A stable identifier (like a token's `sub`) that points to a person without naming them; the name is looked up elsewhere, under its own access rules. | 23 |
| Pull request (PR) | A request to review a branch and merge it into `main`. | 4 |
| Pull vs push (metrics) | Prometheus either fetches (scrapes) `/metrics` from a target (pull), or receives metrics sent to it, here over OTLP from the Collector (push). | 20 |
| Push / pull | Send your commits to the remote / fetch other people's commits from it. | 4 |
| pyproject.toml | The standard Python project file listing the dependency ranges you'll accept (PEP 621). | 2 |
| Quantization | Storing each of a model's numbers in fewer bits (8-bit, 4-bit): smaller and faster, at the cost of a little accuracy. | 7 |
| Query decomposition | An LLM splits a compound question ("X and Y?") into simpler sub-questions that are each searched, so each part finds its own document. | 32 |
| Query instruction | A one-sentence task description prefixed to queries (not documents) for instruction-aware embedders: `Instruct: {task}\nQuery:{query}`. | 8 |
| Query rewriting | Turning the question into a better search query; for a follow-up ("how do I fix it?"), rewriting it as a standalone question using the conversation. | 32 |
| Query transformation | Changing what is searched for before retrieval: expanding acronyms, rewriting, paraphrasing, imagining an answer, splitting or generalising the question. | 32 |
| `rate()` / `increase()` | PromQL functions for counters: `rate` is the per-second speed over a window, `increase` the total growth over it. Both handle counter resets when a process restarts; neither can see a counter's first appearance as growth. | 20 |
| Quorum (replication) | "Any N of the replicas" must confirm: with `method: any, number: 1`, a commit waits for one replica, whichever is fastest. | 37 |
| RAG architecture | The overall design of how a RAG system gathers context and checks its answer (naive, advanced, corrective, agentic…); here, the component in the `pipeline` slot. | 35 |
| Rate limit (RPM / TPM) | How many requests per minute / tokens per minute a key may use; going over returns 429 Too Many Requests. | 10 |
| Raw zone (bronze) | The part of a data platform holding immutable original data, from which everything else can be rebuilt. | 14 |
| RBAC (role-based access control) | Deciding what each user, key or token may read or write by the role or permissions it carries. | 12 |
| recall@k | The share of the relevant documents found in the top k results. "Did we find what matters?" | 26 |
| Recency boost | Blending relevance with freshness (a half-life on a date in the chunk's metadata), so the 2026 policy outranks the 2021 one when both are about equally relevant. | 32 |
| Recording rule | A PromQL query Prometheus pre-computes on every evaluation and stores under a new name (e.g. `rag:search_errors:ratio_rate1h`), so dashboards and alerts stay fast and consistent. | 20 |
| Re-indexing | Re-embedding every stored document because the embedding contract changed; planned like a migration. | 8 |
| Read-only filesystem (container) | Starting a container so it can't write to its own files (`read_only: true`), with a small RAM `tmpfs` for scratch space; here code ownership by root gives the same protection because Compose can't combine it with environment-sourced secrets. | 17 |
| Realm | A separate, self-contained space in Keycloak with its own users, groups, apps and settings. `master` is only for running Keycloak itself; our apps use `rag`. | 16 |
| Realm role | A Keycloak role that says what someone may DO (`rag-user`, `rag-admin`, `rag-auditor`, `rag-ingest`). Here roles are attached to groups, never to people directly. | 16 |
| ReBAC (relationship-based access control) | Access decided by relationships between people and things ("editors of this folder", "shared with Bob"); implemented by OpenFGA and SpiceDB. | 18 |
| Recall | Of the truly closest results, the share the fast (approximate) search actually returned. | 11 |
| Receiver / processor / exporter | The Collector's building blocks: a receiver takes data in (OTLP), a processor changes it (limit, scrub, redact, label, batch), an exporter sends it out (debug, Prometheus, Tempo…). | 19 |
| Recipient | Someone (or a machine) whose public key can open a SOPS file: you, CI, a teammate. | 6 |
| Red teaming | Deliberately attacking your own system to find what gets through; each attack found becomes a regression case in `examples/eval/guards.yaml`. | 34 |
| Redaction | Masking a value that looks like a secret (`****`) so the record survives but the secret doesn't; the Collector's safety net for JWTs, keys and emails. | 19 |
| Redaction (guards) | Replacing the sensitive parts of a payload (an email address, a key, an unsupported sentence, a poisoned document) while keeping the rest; a guard's `redact` verdict. | 34 |
| Reference implementation | The simple, obviously correct version of a component (exact cosine search, textbook BM25) that faster real implementations are compared against. | 30 |
| Refresh token | A longer-lived token an app swaps for new access tokens without signing in again; here it is one-time use and dies at logout. | 16 |
| Refusal accuracy | How often the system says "I don't know…" when the documents really don't contain the answer. | 26 |
| Regal | The linter and editor language server for Rego: catches bugs and style problems in policies; part of `just policy-check`. | 18 |
| Registry (components) | The phone book of components: kind + name → how to build it, its parameters, a summary and its test status (`rag components`). | 30 |
| Rego | OPA's policy language: you write rules that become true or produce values, and OPA evaluates them against `input` and `data`. | 18 |
| Regression | A change that makes a metric worse. | 26 |
| Relational database / table / row / column | Data stored in tables; each row is a record (one chunk), each column a field (its text, its vector). | 11 |
| Remote / origin | A copy of the repository on a server (GitHub); `origin` is its default nickname. | 4 |
| Remote write | The Prometheus protocol for pushing samples into a Prometheus server (enabled with `--web.enable-remote-write-receiver`); Tempo uses it to deliver span metrics and the service graph. | 21 |
| Renew (lease) | Extending a lease before it expires, up to its max TTL. For our database logins a renewal also moves the Postgres VALID UNTIL forward. | 28 |
| Repository | The project's filing cabinet: all files plus their full history of changes (git). | 4 |
| Required action | Something a user must do at their next sign-in: change a temporary password, set up MFA (`CONFIGURE_TOTP`), verify an email. | 16 |
| Reranking | Re-ordering the best few dozen candidates with a stronger, slower model (a cross-encoder or an LLM) that reads the question and each passage together. | 32 |
| Rescoring | After a fast search on compressed vectors, re-ranking the top candidates using the original vectors to recover accuracy. | 12 |
| Residual risk | The risk that remains after the controls; recorded per threat (Low / Medium) and agreed with someone who owns it. | 36 |
| Resource (OpenTelemetry) | Facts about the process sending telemetry (`service.name`, version, environment), attached to every span and metric. | 19 |
| ResourceQuota | A ceiling for a whole namespace: total CPU and memory requests and limits, number of pods. | 29 |
| Response wrapping | OpenBao hands out a secret inside a single-use envelope (a wrapping token with a short TTL). If someone opened it first, the real recipient's unwrap fails, so the theft is noticed. | 28 |
| Restart policy | The rule Docker uses to restart a container that stops or crashes (`restart: unless-stopped`). | 9 |
| Restore drill | Actually restoring a backup into a scratch database and checking it (checksum, row counts), on a schedule: a backup never restored is a hope. | 36 |
| Retention | How long a store keeps data before deleting it: 7 days for traces (Tempo `block_retention`) and logs (Loki `retention_period` plus `compactor.retention_enabled`). | 21 |
| Retention rule | How long an indexed source may stay after it was last ingested, matched by a glob on its URI; `rag retention` reports, then (with `--apply`) deletes what outlived it. | 36 |
| Retrieve-then-rerank | The two-stage search pattern: a fast embedder finds ~50 candidates, then a slow, precise reranker picks the best few for the LLM. | 8 |
| Retry | Trying the same model again after a temporary error, before any fallback. | 10 |
| Reverse proxy | A server that sits in front of other servers, receives every request, applies rules and forwards it. | 9 |
| Review interval | How often a card must be re-read and re-confirmed (e.g. every 90 or 180 days); overdue reviews warn and fail the weekly strict run. | 25 |
| Review queue | The answer ids online evaluation flags for a person to read (thumbs down, groundedness flags); real problems become new labelled questions. | 37 |
| Revocation | Making an old secret stop working, e.g. deleting an API token. | 6 |
| Revocation (access) | Taking access to a document away. It must reach every copy (every store, the graph, the manifest, cached answers) or it hasn't happened: `rag reacl`. | 36 |
| Revoke (lease) | Ending a lease early. For a database login: end its sessions and drop the user, immediately (`bao lease revoke`). | 28 |
| RFC 3161 timestamp | A signed statement from a timestamping authority that some hash existed at a given time. | 23 |
| Right to erasure | A person's right to have their data removed (GDPR Art. 17; under the Australian Privacy Principles, destroying or de-identifying information no longer needed, APP 11.2). | 36 |
| Role / privilege (database) | A database identity / what it's allowed to do (connect, read, write, create tables). | 11 |
| Role mapping | The link in OpenSearch's security plugin that gives a user (or backend role) the permissions of a role. | 13 |
| Rolling update | Replacing pods a few at a time; with `maxUnavailable: 0`, a new pod must be ready before an old one goes. | 29 |
| Root token | An all-powerful OpenBao login created at initialisation. Used once for setup, then revoked; a new one needs 2 key shares (break-glass). | 28 |
| rotate-root | OpenBao changes the password of its own database admin login to a random value, so no person knows it any more. | 28 |
| Rotation | Replacing a secret with a new value on a schedule, or immediately after a suspected leak. | 6 |
| Routing | Choosing which real backend (deployment) answers a request for a given model alias. | 9 |
| Routing (alerts) | Alertmanager's tree of matchers that sends each alert to a receiver: here `severity="critical"` goes to `platform-team-urgent` (page), everything else to `platform-team` (ticket). | 20 |
| Row-level security (RLS) | Rules inside the database that decide which rows a query may see, whatever the query says; here keyed by a per-transaction `rag.tenant` setting, so a query that forgets the tenant returns nothing. | 36 |
| RPO / RTO | Recovery point objective: how much data you can afford to lose. Recovery time objective: how long you can afford to be down. | 36 |
| RRF (Reciprocal Rank Fusion) | The default way to merge ranked lists: each chunk scores 1/(60 + its rank) in every list it appears in, summed. Uses only positions, so it needs no tuning. | 32 |
| Rule (Rego) | A named statement such as `allow if { ... }`, true when every line in its body is true; several rules with the same name mean OR. | 18 |
| Runbook | Step-by-step instructions linked from an alert: what it means, what to check first, likely causes, how to fix, how to close. Every alert here links one under `docs/runbooks/`. | 20 |
| Runner (hosted, self-hosted) | The machine that runs a CI job: GitHub-hosted (a fresh VM each time) or self-hosted (your own, e.g. the Mac with the models; never for fork code). | 27 |
| S3 endpoint | The server URL to send S3 requests to (here `http://127.0.0.1:8333`), passed to tools as `--endpoint-url` / `endpoint_url`. | 14 |
| Safety classifier | A model that labels text as safe or unsafe by category (Llama Guard, ShieldGemma, Granite Guardian); used here through the `llm-judge` guard. | 34 |
| Salt key (LITELLM_SALT_KEY) | A secret LiteLLM uses to encrypt credentials it stores in its database; it must never change, or those become unreadable. | 10 |
| Sampling (head / tail) | Keeping only some traces. Head sampling decides when a request starts; tail sampling decides after seeing the whole trace (e.g. keep all errors and slow ones). | 19 |
| SBOM (software bill of materials) | The list of every component in an artefact, with versions: the ingredients list for an image, so you can tell which images contain a vulnerable library. | 27 |
| Scalar quantization (int8) | Storing each vector number as a 1-byte integer instead of 2–4 bytes: about 4× smaller and faster to scan. | 12 |
| Schema (database) | A named folder of tables inside a database (we use `rag`); also "the structure" of the tables. | 11 |
| Score (LLM evaluation) | A judgement attached to a trace: thumbs up/down, a 0–1 rating, or an evaluator's verdict. | 22 |
| Score normalisation | Rescaling scores from different methods to the same range (min-max: best = 1, worst = 0) before combining them. | 13 |
| Scrape | Prometheus fetching a target's `/metrics` page on a schedule (every 15 s here), optionally with a bearer token read from a secret file. | 20 |
| Seal / unseal | OpenBao's data on disk is encrypted. After every start it is sealed (can't read its own data) until enough key shares are entered to rebuild the unseal key in memory. | 28 |
| Search engine | A system built to find documents by their words (and now vectors) fast, with relevance ranking; e.g. OpenSearch, Elasticsearch. | 13 |
| Search pipeline | Processing steps OpenSearch applies around a search, e.g. normalising and combining scores for hybrid search (`rag-hybrid`). | 13 |
| Search-path hijacking | Tricking a privileged database function into calling an attacker's look-alike object; prevented by fixing the function's `search_path` (with `pg_temp` last). | 23 |
| Secret | Any value that grants access: a password, API key, token, private key or encryption key. | 6 |
| Secret file / /run/secrets | A secret delivered to a container as a small in-memory file, the standard Docker and Kubernetes pattern. | 6 |
| Secret scanner | A check (e.g. gitleaks, detect-private-key) that looks for keys, tokens and passwords before they are committed. | 5 |
| Secrets engine | An OpenBao plug-in that produces secrets: KV v2 stores fixed values, the database engine creates logins. | 28 |
| Secrets manager | A server whose job is to store secrets and hand them out to the right clients, with an audit trail; here OpenBao. | 28 |
| SecretStr | A pydantic type that prints as `**********`; the real value needs a deliberate `.get_secret_value()`. | 6 |
| `SECURITY DEFINER` | A Postgres function that runs with the rights of its owner, not its caller; lets rag-api append audit events without any rights on the table. | 23 |
| Security plugin | OpenSearch's built-in TLS, users, roles and permissions; never disable it. | 13 |
| Self-reflective RAG (Self-RAG) | The system critiques its own answer against the sources and retrieves more and regenerates if it falls short; the `self-reflective` architecture. | 35 |
| Semantic chunking | Cutting a text where the topic changes, found where the embeddings of neighbouring sentences stop being similar. | 31 |
| Semantic conventions | Agreed attribute names (`http.request.method`, `gen_ai.request.model`) so every tool understands the data. | 19 |
| Semantic Versioning | MAJOR.MINOR.PATCH version numbers: breaking change → major, `feat` → minor, `fix` → patch. | 4 |
| Sentence window | A chunking strategy that searches single sentences (precise) and gives the model the sentences around the match (context). | 31 |
| Server-sent events (SSE) | A simple web standard for a server to push a stream of `event:` / `data:` messages over one HTTP response; how `/v1/answer` streams its meta, delta and done events. | 33 |
| Service (Kubernetes) | A stable name and address for a set of pods, found by labels and a selector; an ExternalName Service is just a DNS alias. | 29 |
| Service account | A non-human identity tied to a confidential client, used with client credentials (e.g. `service-account-ingestion-worker`). | 16 |
| Service graph | Who-calls-whom metrics (`traces_service_graph_request_total{client, server}`) that Tempo computes from client/server spans; Grafana draws them as boxes and arrows. | 21 |
| ServiceAccount (Kubernetes) | A pod's identity inside the cluster; OpenBao trusts tokens issued for `rag:rag-api`. | 29 |
| Session / user / tags | Ways to group LLM traces: a conversation, a (pseudonymous) person, free-form labels. | 22 |
| SHA-256 | A hash function producing a 32-byte fingerprint: the same input always gives the same output, one changed bit changes it completely, and it can't be reversed or collided in practice. | 23 |
| Shadow price | An internal, notional price for something with no bill (your own GPU time), so usage can be compared and budgeted; here $2/hour ÷ tokens per second. | 10 |
| Shamir's secret sharing | Splitting a key into N shares so that any K of them rebuild it and fewer reveal nothing. OpenBao's unseal key: 3 shares, any 2. | 28 |
| Shard / replica | The pieces an index is split into / copies of them for safety; one node uses 1 shard and 0 replicas. | 13 |
| shared_buffers | Postgres's own memory cache for table and index pages, typically about 25% of the memory it may use. | 11 |
| Shell / zsh | The program inside Terminal that reads and runs your commands; zsh is the macOS default. | 1 |
| Shift left | Moving checks earlier in the process (editor, commit) where fixing problems is cheapest. | 5 |
| Showback / chargeback | Showing each team what it used / actually billing its cost centre for it. | 10 |
| Side door | A way to read data around the access policy, for example a trace viewer showing documents the reader isn't cleared for. | 22 |
| Signal | One kind of telemetry: traces, metrics or logs. | 19 |
| Signed commit | A commit stamped with your private key so GitHub can show it as Verified (really from you). | 4 |
| Significance test | A check that a difference between two rates is bigger than chance would explain given how many answers you have (here a one-sided two-proportion z-test). | 37 |
| Sigstore (cosign, Fulcio, Rekor) | Free signing infrastructure: cosign signs and verifies, Fulcio issues short-lived certificates for an OIDC identity, Rekor is the public transparency log of signatures. | 27 |
| Silence | A deliberate, time-limited mute of matching alerts in Alertmanager, e.g. during planned maintenance; stored so it survives restarts. | 20 |
| Single source of truth | Each fact lives in exactly one file; other places check it rather than copy it. | 25 |
| Single-pass rendering | Filling placeholders once: text that was inserted is never scanned again, so a user typing `{{context}}` can't pull in other values. | 24 |
| SLI / SLO / SLA | Service level Indicator (what you measure, e.g. the share of searches that succeed) / Objective (your internal target, 99% over 28 days) / Agreement (the contractual promise to customers, set looser than the SLO). | 20 |
| Slot | A role in a RAG pipeline (`vector_store`, `reranker`, `guards`, …) that one component, or a list for plural slots, fills; its kind says which components may. | 30 |
| SLSA | Supply-chain Levels for Software Artifacts ("salsa"): a framework of levels for how trustworthy a build and its provenance are. | 27 |
| Smoke test vs benchmark | A handful of cases that catch obvious breakage, vs hundreds that measure quality reliably. Eight cases is a smoke test: one case moves the score by 12.5 points. | 26 |
| Snapshot | A point-in-time backup file of a collection. | 12 |
| Soak period | How long the old version is kept after a switch (e.g. the previous collection after a re-index), so rolling back stays a simple revert. | 36 |
| Soak time | How long a release must run in one environment (24 hours in staging here) before it may be promoted further. | 37 |
| Software supply chain | Everything your software is made from and with: dependencies, tools, CI actions, base images and the build itself. | 27 |
| SOPS | "Secrets OPerationS": encrypts the values in YAML, JSON or `.env` files while leaving the names readable. | 6 |
| Source of truth | The one authoritative store that decides what exists and who may see it; every other copy is derived from it. | 12 |
| Span | One timed step in a request: name, start, duration, status and attributes. | 19 |
| Span metrics | Request rate, errors and duration per service and span name (`traces_spanmetrics_*`), computed from traces by Tempo's metrics generator. | 21 |
| Sparse (keyword) retrieval | Search by words: BM25 or Postgres full-text search. Finds exact codes and names ("E-4021") but misses synonyms. | 32 |
| Sparse vector | A vector that's mostly zeros, stored as (position, value) pairs; used for keyword-like retrieval (SPLADE, BM25-style). | 12 |
| SPDX licence id | The standard short name for a licence (`apache-2.0`, `mit`), so tools can compare them. | 25 |
| Speculative decoding | A small draft model guesses a few tokens ahead and the big model checks them in one pass, speeding up decoding (`--draft-model`). | 7 |
| SQLite authorizer | A callback SQLite runs for every action a statement wants to take (read a table, write, attach a database…); here it allows only reading the tables the person may see. | 35 |
| Squash merge | Merging a PR so all its small commits become one clean commit on `main`. | 4 |
| src layout | Putting a package's code under `src/<name>/` so tests import the installed package, not the raw folder. | 4 |
| SSDLC | Secure Software Development Lifecycle: building security checks (static analysis, secret scanning) into every change. | 5 |
| SSH key | A private key that stays on your Mac and a public `.pub` key you give GitHub, to prove it's you without a password. | 4 |
| SSO session | Your sign-in at Keycloak itself. While it lasts (30 idle minutes, 10 hours at most here), other apps sign you in without asking again. | 16 |
| Staged files | The files you have `git add`-ed: exactly what the next commit will contain, and what hooks check. | 5 |
| Status: live / mocked / reference | How a rag-core component is tested here: against the real service, against its exact HTTP requests, or not at all (needs heavy extras). | 30 |
| Stemming | Reducing words to a common root ("Fridays" → "fridai") so variations of a word match. | 13 |
| Step-back prompting | An LLM writes a more general question about the principle behind the user's question; searching both finds the background policy as well as the specific rule. | 32 |
| Stream (Loki) | All log lines that share exactly the same set of labels; each unique label combination is a separate stream, so labels must have few values. | 21 |
| Stream (Valkey/Redis) | An append-only log of messages, each with an increasing ID (`XADD`); with consumer groups it works as a crash-safe job queue. | 15 |
| Streaming (SSE) | Sending an answer token by token as it is generated, over Server-Sent Events, instead of all at the end. | 9 |
| STRIDE | A checklist of threat categories: Spoofing, Tampering, Repudiation, Information disclosure, Denial of service, Elevation of privilege. The register adds Safety. | 36 |
| Structure-aware chunking | Cutting along a document's own structure: never across a heading, tables and code kept whole, each chunk labelled with its heading path. | 31 |
| Structured logging | Writing logs as JSON objects instead of free text, so they can be filtered and joined by field. | 19 |
| Structured metadata (Loki) | Extra per-line key/value facts (such as OTLP attributes) that Loki stores and can search without turning them into labels, so they don't create new streams. | 21 |
| Supersede | Replace an accepted ADR with a newer ADR that points back to it; the old one is never edited. | 4 |
| Supply-chain attack | Poisoning something your software is built from (a library, an action, a tool binary, a base image) instead of attacking the application itself. | 27 |
| Sync / prune / self-heal / sync wave | Argo CD's verbs: apply git; delete what git no longer has; undo hand-made changes; order syncs (lower waves first). | 29 |
| Synchronous replication | A write counts as committed only when a replica also has it, so losing the primary loses no committed write. | 37 |
| Synonyms (search) | Rules treating different terms as equivalent ("wfh" = "work from home" = "remote work"), best applied at query time with `synonym_graph`. | 13 |
| System card | A short document about an application built from models and data: purpose, users, human oversight, risk assessment. | 25 |
| Table lock | A lock on a whole table; `LOCK TABLE … IN EXCLUSIVE MODE` lets only one writer append at a time (so the chain can't fork) while readers carry on. | 23 |
| Tamper-evident vs tamper-proof | Evident: changes can't be hidden. Proof: changes are impossible. Nothing digital is tamper-proof against its own administrators; evident is the honest goal. | 23 |
| Target (system under test) | The thing an evaluation runs against: here, retrieval-with-policy as a persona, or one prompt version on one model. | 26 |
| Team (LiteLLM) | A group of virtual keys sharing a budget and a model list, e.g. a department or product. | 10 |
| TEI (Text Embeddings Inference) | Hugging Face's Rust server for embedding and reranking models, with batching, API keys and metrics; runs natively with Metal on Apple Silicon. | 8 |
| Telemetry | Usage information a program sends to its makers; switched off on purpose (Qdrant here, Homebrew analytics in Step 1). | 12 |
| Telemetry (observability) | The data a system reports about itself (traces, metrics, logs) for its own operators; not to be confused with usage data sent to a vendor. | 19 |
| Term frequency (tf) | How often a query word appears in a document; more helps in BM25, with diminishing returns. | 13 |
| Template (OpenBao Agent) | An agent setting that renders a secret into a file (path, permissions, format), and re-renders it when the secret changes, writing aside and renaming so readers never see half a file. | 28 |
| Tempo | Grafana's trace store: keeps every span cheaply in blocks, finds traces by id or TraceQL, and can generate metrics from them. | 21 |
| Test case | One question in a golden dataset, with what a good result must (and must not) contain. | 26 |
| Text layer | The text stored inside a digital PDF; a scanned PDF is only pictures of pages and has none, so it needs OCR. | 31 |
| text vs keyword field | `text` is analysed for full-text search; `keyword` is stored exactly, for filters and IDs. | 13 |
| Text-to-SQL | A model writing a database query from a question; the `sql` architecture, where the result becomes a cited source. | 35 |
| Thinking mode | Qwen models' optional hidden reasoning before the answer; better on hard questions, slower and more tokens (`enable_thinking`). | 7 |
| Threat model | A structured list of what could go wrong with a system, who could cause it, and what stops it; here generated from `docs/compliance/risk-register.yaml`. | 36 |
| Threshold | The minimum or maximum a metric must reach for a run to pass the gate, e.g. `recall@5: {min: 0.9}` or `leaked_docs: {max: 0}`. | 26 |
| Throughput | How much work a server finishes per second, e.g. chunks embedded per second. | 8 |
| Time series | One metric with one exact set of labels, sampled over time, e.g. `rag_search_requests_total{outcome="ok"}`. | 20 |
| Token | The unit a model reads and writes: roughly ¾ of an English word. | 7 |
| Token (OpenBao) | What a successful OpenBao login returns: a credential with policies and a TTL, sent as `X-Vault-Token` on every request. Not the same as a model's token. | 28 |
| Token budget | The share of the model's context window given to retrieved documents (3000 tokens by default), leaving room for the instructions, the question and the answer. | 33 |
| Token filter | An analyzer step that changes the token stream: lowercase, synonyms, stemming. | 13 |
| Token introspection (RFC 7662) | Asking the identity provider "is this token still valid?" on every request: instant revocation, at the cost of a network call each time. | 17 |
| Token revocation | Cancelling a token before it expires. With local validation it only takes full effect when the (5-minute) access token expires. | 17 |
| Token validation | Proving a token is genuine and meant for you (signature, algorithm, issuer, audience, expiry, type, calling app) before believing anything in it. | 17 |
| Tokenizer | The model's dictionary for converting text to tokens and back. | 7 |
| Tokenizer (search) | The analyzer step that splits text into words (tokens); not the same as an LLM's tokenizer. | 13 |
| Tokens per second (tok/s) | How fast an answer streams once it starts; mostly set by memory bandwidth. | 7 |
| Toxicity | Insulting, hateful or abusive language; checked here with a small word list as a baseline to replace with a classifier. | 34 |
| Trace | All the spans of one request, across all services, sharing one trace id. | 19 |
| Trace backend | A store that keeps traces and finds them by id or by query (Tempo here; Jaeger is another). | 21 |
| traceparent (W3C Trace Context) | The standard HTTP header that carries the trace id and parent span id to the next service. | 19 |
| TraceQL | Tempo's query language for finding traces by span facts, e.g. `{resource.service.name="rag-api" && duration > 2s}`. | 21 |
| Transitive dependency | A dependency of a dependency: a package you never chose that comes along because one you chose needs it. | 2 |
| Transparency log | A public append-only log built on a Merkle tree (Certificate Transparency, Sigstore Rekor) that lets outsiders verify entries without trusting the operator. | 23 |
| Trigger (database) | Code the database runs automatically before or after a change; here a statement trigger that refuses any change to the audit table. | 23 |
| Truncation / max sequence length | The longest text a model reads; anything beyond is cut off, silently in TEI by default (`--auto-truncate`). | 8 |
| Trunk-based development | `main` (the trunk) is always working; every change goes through a short-lived branch and a PR. | 4 |
| Trust on first use (TOFU) | Recording a hash from your first download when the publisher provides none (dbmate here), and refusing anything different later; weaker than a published checksum. | 27 |
| TTFT (time to first token) | How long you wait before the first word appears; mostly set by prefill and prompt length. | 7 |
| TTL (default, max; OpenBao) | How long a lease or token lives: the default TTL when issued (1 h for our logins) and the max TTL it can be renewed up to (24 h for rag-api). | 28 |
| TTL (time to live) | An expiry time on a key; it disappears automatically afterwards. Every cache entry gets one. | 15 |
| Type checker | A tool (e.g. `mypy`) that reads type hints and checks they are used consistently, catching wrong-kind-of-value bugs before running. | 5 |
| Type hint | A label saying what kind of value a variable or function expects or returns, e.g. `def chunk(text: str) -> list[str]`. | 5 |
| Unified memory | Apple Silicon memory shared by the CPU and GPU; every GB given to the container VM is a GB the models lose. | 3 |
| Upstream | Everything a component was built from, directly or indirectly (`just cards lineage`). | 25 |
| uv | Astral's all-in-one Python tool: interpreters, virtual environments, locking and tool installs. | 2 |
| ValidatingAdmissionPolicy | Your own admission rule, written in CEL and run inside the API server (GA since Kubernetes 1.30): no extra controller needed. | 29 |
| Valkey | The open-source (BSD), Redis-compatible in-memory store maintained under the Linux Foundation, forked from Redis in 2024 after Redis's licence change. | 15 |
| Vault (HashiCorp) | The best-known secrets manager. Its licence changed to BUSL-1.1 in 2023 (not open source); we say "Vault" for the idea and use OpenBao, its open-source fork. | 28 |
| Version (prompt) | One frozen edition of a prompt, a file `prompts/<name>/v<N>.yaml`; `rag-answer@2` always means the same text. | 24 |
| Versioning / version ID | Keeping every overwrite of an object as a separate version, each with its own ID, so nothing is silently lost. | 14 |
| Virtual environment | A private folder of packages (`.venv`) for one project, tied to one interpreter. | 2 |
| Virtual key | A per-app or per-person key issued by the gateway, with its own budget, limits and allowed models; needs a database (Step 10). | 9 |
| Virtual machine (VM) | A computer simulated inside your computer; on a Mac, containers run inside a small Linux VM. | 3 |
| WAL archiving | Copying Postgres's write-ahead log to object storage continuously, so the database can be replayed to any second. | 37 |
| Wheel | A pre-built Python package, ready to install, like flat-pack furniture. | 2 |
| Wired memory / GPU working-set limit | The share of unified memory macOS lets the GPU lock for itself (`iogpu.wired_limit_mb`); large models need it big enough. | 7 |
| Workflow / job / step | GitHub Actions' structure: a workflow (YAML file) has jobs that run in parallel on fresh machines, and each job has steps (commands or actions). | 27 |
| Workload identity | Each program logs in as itself (its own Kubernetes service account and OpenBao role), with only its own permissions. | 37 |
| Workspace (uv) | Several Python packages in one repository sharing one `uv.lock` and one `.venv`. | 4 |
| WORM (write once, read many) | Storage where data can be written once and then never changed or deleted until its retention ends; what object lock provides. | 14 |
| `WWW-Authenticate` | The response header on a 401 telling the client a bearer token is required, or (with `error="invalid_token"`) that the one sent was not accepted. | 17 |
| `yaml.safe_load` | Reads YAML as plain data only. The unsafe `yaml.load` can construct Python objects, so a hostile file could run code. | 24 |
| Zanzibar | Google's paper and system for relationship-based authorisation at global scale; the model behind OpenFGA and SpiceDB. | 18 |
