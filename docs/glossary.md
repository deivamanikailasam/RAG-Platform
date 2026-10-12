# Glossary

Plain-English definitions of the terms introduced across the build guide, in alphabetical order.
The number in brackets is the step where the term first appears; see [`docs/steps/`](steps/README.md).

| Term | Meaning | Step |
|---|---|---:|
| 0.0.0.0 / * | "Every interface": a port bound here is reachable by anyone who can reach your machine on the network. | 3 |
| 401 vs 403 | 401 Unauthorized means "I don't know who you are" (no token, or a bad one); 403 Forbidden means "I know who you are, and the answer is no" (a valid token without the needed role). | 17 |
| ABAC (attribute-based access control) | Access rules based on facts (attributes) about the person and the thing, such as classification, clearance or department, rather than just roles; what OPA evaluates here. | 18 |
| Access token | The short-lived (5-minute) token an app shows to an API on every call; it carries who you are, your groups and roles, and when it expires. | 16 |
| Acknowledgement (XACK) | A worker's "done" signal for a stream message. Until it arrives, the message stays pending for that worker. | 15 |
| ACL (access control list, Valkey) | Per-user rules for which keys (`~pattern`), pub/sub channels (`&pattern`) and commands (`+@category`, `-@category`) a user may use; `user default off` disables anonymous access. | 15 |
| Active parameters | In a Mixture of Experts model, the parameters actually used for each token (about 3B in Qwen3.6-35B-A3B, the "A3B"); they set the speed. | 7 |
| Admin events (Keycloak) | Keycloak's record of every administrative change (user created, group membership added, lockout cleared), with the full details when enabled; audit evidence for "who changed what". | 16 |
| ADR (Architecture Decision Record) | A short Markdown file recording one significant decision: context, decision, alternatives and consequences. | 4 |
| age | A small, modern encryption tool with short keys (`age1…`); makes the key pair SOPS uses. A simpler, safer replacement for GPG. | 6 |
| Alert rule | A PromQL condition Prometheus checks every evaluation; when it has stayed true for the rule's `for` duration, the alert fires and goes to Alertmanager with its labels (e.g. `severity`) and annotations (summary, runbook). | 20 |
| Alertmanager | The service that receives firing alerts from Prometheus and decides what to do with them: group, de-duplicate, silence, inhibit and route each to the right receiver (a page, a ticket, a chat channel). | 20 |
| `alg: none` | A token header claiming the token is unsigned. Some old libraries accepted such tokens as valid, a famous vulnerability; our verifier never does. | 17 |
| Algorithm allow-list | The fixed list of signing algorithms a verifier accepts (only `RS256` here), chosen by the server, never by the token, so an attacker can't pick a weaker one. | 17 |
| Algorithm confusion | An attack that re-signs a token with HS256 using the server's PUBLIC key as the HMAC password; blocked by allowing only RS256. | 17 |
| Alias (Qdrant) | A stable name (`rag_chunks`) pointing at a real collection; applications use it, and it can be switched to another collection instantly and atomically. | 12 |
| Allow-list | The only models a key may use; a request for anything else is refused (401/403). | 10 |
| Analytics | Anonymous usage statistics a tool sends back to its makers. | 1 |
| Analyzer | The recipe a search engine uses to turn text into searchable terms: a tokenizer plus token filters (lowercase, synonyms, stemming). | 13 |
| Anchoring (audit log) | Copying the newest hash of a chain (and the events) somewhere the database's administrators can't change, such as an object-locked bucket, so a later rewrite of the chain becomes visible. | 23 |
| ANN (approximate nearest neighbour) | Finding nearly the closest vectors very fast, instead of exactly the closest by checking every one. | 11 |
| Append-only | Rows may be added, never changed or removed; enforced here by a trigger that refuses `UPDATE`, `DELETE` and `TRUNCATE`, even for the table's owner. | 23 |
| arm64 / aarch64 vs amd64 / x86_64 | Processor families; Apple Silicon is arm64, amd64-only images need slower emulation. | 3 |
| Asymmetric retrieval | Embedding questions and documents differently (queries get a task instruction, documents don't), because a short question and a long passage are different kinds of text. | 8 |
| At-least-once delivery | Every job is delivered at least once, but may be delivered twice after a crash (the worker finished but died before acknowledging). | 15 |
| Attributes (span) | Key–value facts recorded on a span, e.g. `rag.candidates = 5`; facts about the request, never its content. | 19 |
| Audience (`aud`) | The claim saying who a token is meant for (here `rag-api`). An API must reject tokens meant for someone else. | 16 |
| Audit log | A permanent, minimal record of security-relevant actions (who, what, when, result), kept for years and protected from tampering. Not for debugging. | 23 |
| Authentication vs authorisation | Who are you? (sign-in) versus what may you do? (permissions). Keycloak does the first and carries the facts (groups, roles) for the second. | 16 |
| Authorisation policy | The written rules that say who may do which action and see which things; here `policies/rag/authz/authz.rego` plus its `data.json`. | 18 |
| Authorization code + PKCE | The sign-in flow for web apps: the browser gets a one-time code and swaps it for tokens, proving with a random "code verifier" (PKCE) that it is the same app that started the sign-in. | 16 |
| Authorization header | The HTTP request header that carries credentials; for APIs it is `Authorization: Bearer <access token>`. | 17 |
| Auto-fix | A check that changes files to fix the problem itself; you review the change and `git add` it again. | 5 |
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
| Brewfile | A plain text file listing Homebrew formulas and casks; `brew bundle` installs everything in it. | 1 |
| Brute-force protection | Temporarily locking an account after several wrong passwords (here 5), with a wait that grows from 60 seconds to 15 minutes. | 16 |
| Bucket / key / object (S3) | A top-level container in object storage / the object's name, which can look like a path but is just a string (`raw/remote.pdf`) / the bytes plus metadata. | 14 |
| Bucket (histogram) | One counter in a histogram: how many values were at or below a fixed edge (`le="0.5"`, `le="2"`…). The edges must be in the metric's unit and should include each objective (2 s here). | 20 |
| Budget / budget period | The maximum spend (here in shadow dollars) a key or team may reach before requests are refused, and how often it resets (e.g. `30d`). | 10 |
| Burn rate | How fast an error budget is being used, relative to the allowed pace. 1× spends it exactly over the period; 14.4× spends a 28-day budget in about 2 days (page); 6× in about 5 days (ticket). | 20 |
| Cache hit / miss | Hit: the answer was already stored and comes back in milliseconds. Miss: it had to be computed (the LLM ran) and is then stored. | 15 |
| Cache key | The value a cache looks answers up by. It must include everything that changes the answer (prompt with retrieved context, model, parameters, user's permission scope, tenant), or answers leak between users. | 15 |
| Cache poisoning | A wrong, stale or someone-else's answer stored in a cache and then served to other requests, e.g. because the cache key left out the permission scope. | 15 |
| Cap (deny overrides) | A limit that beats any grant: a contractor in `executives` still only reaches `internal`, because caps in `capped_groups` always win over group clearances. | 18 |
| Cardinality | How many distinct values a label has. User ids as metric labels create one time series per user: slow dashboards and big bills; keep labels to small fixed sets like `outcome` = ok or error. | 19 |
| Cask | A Homebrew package that is a normal Mac app with a window. | 1 |
| Chat template | The model-specific recipe that turns a list of messages into the exact text format the model was trained on. | 7 |
| Ciphertext | The scrambled, encrypted version of a value; unreadable without the right key. | 6 |
| Claim | One field in a token's payload, such as `iss`, `sub`, `groups` or `exp`. | 16 |
| Clearance | The highest classification (public < internal < confidential < restricted) a person may read, taken from their groups; no known group means no clearance at all. | 18 |
| CLI | Command-line interface: a program you control by typing commands. | 1 |
| ClickHouse | A fast column-oriented analytics database; Langfuse stores traces, observations and scores in it. | 22 |
| Client (OIDC) | An app registered with the identity provider. Public clients (browser, command line) can't keep a secret; confidential clients (servers, workers) can. | 16 |
| Client credentials | The flow where a machine signs in with its own client id and secret, with no person involved; it gets an access token but no refresh token. | 16 |
| Client scope | A reusable bundle of protocol mappers (and other token settings) that can be attached to many clients instead of repeating the mappers on each. | 16 |
| Clock skew / leeway | Small differences between machines' clocks; a tolerance (30 s here) stops a verifier from rejecting a token that is only just fresh or only just expired. | 17 |
| CODEOWNERS | A GitHub file naming who must review changes to which folders. | 4 |
| Collection (Qdrant) | Qdrant's equivalent of a table: a set of points sharing vector settings. | 12 |
| Collector (OpenTelemetry) | A service that receives, processes and exports telemetry; our single governance point that limits memory, scrubs secrets, redacts values, labels and batches (`otel-collector`). | 19 |
| Command category (Valkey) | A named group of commands used in ACLs, e.g. `@dangerous` (FLUSHALL, KEYS, CONFIG, DEBUG…) or `@admin`; `+@all -@dangerous` means everything except those. | 15 |
| Command Line Tools | Apple's free kit of basic developer programs: compiler, `make`, `git`, system headers. | 1 |
| Commit | A save point in git history, with a message explaining what changed and why. | 4 |
| Compiler | A program that turns human-written source code into a program the computer can run. | 1 |
| Compose project | The group of containers, networks and volumes one Compose file starts, sharing a name (`name: rag-platform`) that prefixes every container (`rag-platform-litellm-1`). | 9 |
| Consumer group | A set of workers sharing one stream; each message goes to exactly one worker in the group, and the group remembers what was delivered and acknowledged. | 15 |
| Container | A running copy of an image: a self-contained "apartment" with a program and everything it needs. | 3 |
| Container runtime | The software that downloads images and runs containers (OrbStack, Docker Desktop, Colima, Podman). | 3 |
| Content addressing | Naming an object by a hash of its content (`sha256`), so identical files share a name and changes are detectable. | 14 |
| Context propagation | Passing the trace id from one service to the next (in the `traceparent` HTTP header) so their spans join one trace. | 19 |
| Context window | The maximum number of tokens (prompt + answer) a model can handle at once. | 7 |
| Conventional Commits | A commit-message format `type(scope)!: description` (e.g. `feat(gateway): …`) readable by people and tools. | 4 |
| Cooldown | Temporarily skipping a backend that keeps failing (LiteLLM: 30 s after 3 failures in a minute), so requests stop piling onto it. | 10 |
| CORS | Browser rules for which websites may call a server from inside a web page; too open (`*`) and any site you visit could call your local model. | 7 |
| Cosine similarity | A score for how closely two vectors point the same way: near 1 = very similar meaning, near 0 = unrelated. For unit-length vectors it equals the dot product. | 8 |
| Counter (metric) | A number that only goes up, such as requests served; dashboards turn it into a rate. | 19 |
| Cross-encoder | A model (the reranker) that reads the query and one document together and scores their relevance; precise but slow, so only used on a shortlist. | 8 |
| Crypto-shredding | Making data unreadable by destroying a key or a lookup instead of deleting it; reconciles "never delete" with the right to erasure (e.g. deleting the Keycloak account behind an audit `sub`). | 23 |
| Dashboards as code | Generating dashboard definitions (Grafana JSON) from reviewed code in Git (`scripts/build_dashboards.py`) instead of clicking in the UI, with a check that fails when the committed JSON is out of date. | 20 |
| Data filtering / partial evaluation (OPA) | OPA evaluating a policy with some facts still unknown and turning the rest into a filter, even a SQL `WHERE` clause, that a database can apply. | 18 |
| Data key | The random key SOPS creates per file to lock every value; it is itself locked once per recipient. | 6 |
| Data retention | How long data is kept before it is deleted; for Langfuse traces, 30 days, enforced by our own nightly job because automatic retention is an Enterprise feature when self-hosted. | 22 |
| Dead-letter queue (DLQ) | Where jobs go after failing too many times (here: 3 deliveries), so they stop retrying forever and a human can inspect them. | 15 |
| Decision log | OPA's record of every decision (input, result, path, time, `decision_id`), written as JSON; the audit evidence for "who was allowed what, and why". | 18 |
| Decode | The second phase of generation: the model writes the answer one token at a time; its speed is limited by memory bandwidth. | 7 |
| Dedicated vector database | A database built only for storing vectors and finding the nearest ones fast, with filters (Qdrant, Milvus, Weaviate), rather than a general database with a vector extension. | 12 |
| `default` (Rego) | The value a rule takes when none of its bodies match, e.g. `default allow := false`; the building block of deny by default. | 18 |
| Default privileges (ALTER DEFAULT PRIVILEGES) | A standing instruction that every table a given role creates from now on automatically gets certain grants, so new tables are never invisible to the app. | 11 |
| Delete marker | With versioning on, "delete" only adds a marker that hides the object; older versions still exist until each is deleted by version ID. | 14 |
| Deny by default | Nothing is allowed unless a rule explicitly allows it; in Rego, `default allow := false`. | 18 |
| Dependency | A package your project needs in order to work. | 2 |
| Dependency group | A named set of extra dependencies in `pyproject.toml` (PEP 735), e.g. `dev` for test tools not needed in production. | 2 |
| Dependency injection (FastAPI) | FastAPI runs helper functions ("get the caller", "require this role") before an endpoint and passes their results in; tests swap them for fakes with `dependency_overrides`. | 17 |
| Deployment (LiteLLM) | One real backend behind a model alias; an alias can have several, for load-balancing or failover. | 9 |
| Derived index | A copy organised for fast lookup, always rebuildable from the source of truth. | 12 |
| Dev dependency | A package needed only while developing (e.g. pytest), not when the app runs in production. | 2 |
| Device flow | The sign-in flow for terminals and TVs: the app shows a link and a short code, you approve in a browser (with password and MFA), and the app receives tokens without ever seeing your password. | 16 |
| Dimensions (of an embedding) | How many numbers an embedding vector has (Qwen3-Embedding-0.6B: up to 1,024); more can hold more nuance but costs storage and search time. | 8 |
| direnv | A tool that loads a project's settings automatically when you enter its folder. | 1 |
| Distance operator | pgvector's comparison symbols: `<=>` cosine distance, `<#>` negative inner product, `<->` Euclidean (L2), `<+>` L1. | 11 |
| Distributed lock | A short-lived "I'm working on this" marker shared by all workers (`SET key token NX PX 30000`): only one holder, expires on its own, released only with the owner's token. | 15 |
| Docker Compose | A file (`compose.yaml`) listing many containers and how they connect; `docker compose up` starts them all. | 3 |
| Docker engine / CLI | The engine runs containers inside the VM; the `docker` command is how you talk to it. | 3 |
| Drift | When the dependency list (`pyproject.toml`) and the lockfile (`uv.lock`) no longer match; `uv sync --locked` catches it. | 2 |
| Dual logging | Docker keeping a local copy of a container's recent output even when a remote logging driver (like `fluentd`) ships it elsewhere, so `docker compose logs` keeps working. | 21 |
| EditorConfig | A small `.editorconfig` file telling every editor the same formatting basics (indentation, line endings). | 4 |
| Embedding / vector | A fixed-length list of numbers representing a text's meaning: a point in meaning space. | 8 |
| Embedding contract | Everything that defines how vectors were made (model + revision, dimensions, query instruction, normalisation, pooling, chunk limit); change any part and the index must be rebuilt. | 8 |
| Encryption | Scrambling data so only someone with the right key can unscramble it. | 6 |
| Endpoint | A specific URL path on a server, e.g. `/v1/chat/completions` or `/health`. | 7 |
| Envelope encryption | Values are locked with a random data key, and the data key is locked separately for each recipient, so adding a person never means re-encrypting every value by hand. | 6 |
| Environment variable | A named value handed to a program when it starts (`DB_PASSWORD=…`); fine for settings, easy to leak for secrets. | 6 |
| Error budget | The amount of failure an SLO allows: with 99% of searches succeeding over 28 days, 1% may fail. Budget left: ship features; budget burning: prioritise reliability. | 20 |
| Eviction / maxmemory policy | What a memory-capped store deletes when it is full. `volatile-lru` removes the least-recently-used keys that have a TTL; `allkeys-lru` may remove any key, including queued jobs. | 15 |
| Exemplar | A sample trace id attached to one metric data point, so a dot on a graph links straight to a real request's trace. | 21 |
| EXPLAIN | Asks Postgres how it will run a query, e.g. whether it uses an index; `EXPLAIN ANALYZE` also runs it and shows real timings. | 11 |
| Explain API | Adding `"explain": true` to a search so OpenSearch returns the arithmetic behind each score (tf, idf, length adjustment). | 13 |
| Exporter (Prometheus) | A small adapter that reads a system's own statistics and serves them as `/metrics` for Prometheus, e.g. `postgres_exporter` for rag-db, logged in as the read-only `rag_metrics` role. | 20 |
| Extension (Postgres) | An add-on that teaches Postgres new tricks; `vector` (pgvector) adds vector types and indexes. | 11 |
| Fail closed | When unsure, deny: no groups in the token means no documents, not all documents; an unreachable key service means 503, not "let it through". | 17 |
| Fail open | The opposite of fail closed: when something breaks or a fact is missing, let the request through. Never acceptable for security; an undefined Rego value can cause it silently. | 18 |
| Fallback | Sending a request to a different model when the first one fails; fine between chat models, never between embedders (different vector spaces). | 10 |
| False positive | A check flags something that is actually fine; silence it narrowly, with a comment explaining why. | 5 |
| FinOps | The practice of making technology spend visible, attributed to teams, and managed against budgets; AI FinOps applies it to model usage. | 10 |
| `for` (alert duration) | How long an alert's condition must stay true before it fires (`for: 2m`). Stops a single wobbly reading from paging anyone. | 20 |
| Formatter | A tool (e.g. `ruff format`) that rewrites code layout into one consistent style without changing what it does. | 5 |
| Formula | A Homebrew package that is a command-line tool. | 1 |
| Full-text search / tsvector | Postgres's built-in keyword search: words normalised to stems (a `tsvector`) and indexed with GIN. | 11 |
| Gateway (AI / LLM gateway) | A server in front of all model servers: every request passes through it for authentication, allow-listing, routing, limits and logging. | 9 |
| GenAI semantic conventions | The emerging standard `gen_ai.*` attribute names for model calls (operation, model, token usage), so LLM tools and vendor dashboards understand each other. | 19 |
| Generation (LLM observability) | An observation for one LLM call: prompt, completion, model, tokens and cost (recorded from Step 33). | 22 |
| Genesis (hash chain) | The starting point of a hash chain: here 32 zero bytes, used as the "previous hash" of row 1. | 23 |
| GIN index | A Postgres "inverted" index for values with many parts: arrays, JSON and words. | 11 |
| Git hook | A script git runs automatically at a set moment: before a commit, after the message is written, before a push. | 5 |
| .gitattributes | Rules for how git treats file types (line endings, binary files, generated files). | 4 |
| .gitignore | A "do not pack" list of files git must never track (secrets, `.venv`, data, models). | 4 |
| Graceful degradation | Continuing with reduced quality or features instead of failing completely, e.g. skipping reranking and flagging the answer when the reranker is down. | 10 |
| Grant / flow | A standard recipe for getting a token: authorization code + PKCE (web apps), device flow (CLIs), client credentials (machines). The password grant (ROPC) is switched off. | 16 |
| Group (Keycloak) | A set of users who are "with" each other (department, team). It decides what you may SEE: its name goes into the token's `groups` claim and matches documents' `acl_groups`. | 16 |
| Grouping (alerts) | Alertmanager combining related alerts (same `alertname` and `service` here) into one notification instead of one per time series. | 20 |
| halfvec | A pgvector type that stores each number in 2 bytes instead of 4: half the storage, negligible quality loss for embeddings. | 11 |
| Hash | A short fingerprint calculated from a file's contents; change one byte and it changes completely. | 2 |
| Hash chain | Records linked by including each previous record's hash in the next one's hash, so editing any record breaks every later link. | 23 |
| Head (hash chain) | The newest hash of a chain; it summarises the entire chain up to that point. | 23 |
| Headless initialisation | Creating an application's organisation, project, API keys and first admin from configuration at first start, with no clicking (Langfuse's `LANGFUSE_INIT_*` variables). | 22 |
| Healthcheck | A command Compose runs inside a container every few seconds to ask "are you working?"; failures mark it unhealthy. | 9 |
| Histogram (metric) | A metric that records a distribution of values (e.g. latencies), from which p50/p95/p99 are computed. | 19 |
| `histogram_quantile` | The PromQL function that estimates a percentile (e.g. p95) from histogram buckets; it can only be as precise as the bucket edges allow. | 20 |
| HNSW | Hierarchical Navigable Small World: a layered graph index for fast approximate vector search, tuned by `m`, `ef_construction` and `hnsw.ef_search`. | 11 |
| Homebrew | The standard package manager ("app store for developer tools") on macOS. | 1 |
| host.docker.internal | The address a container uses to reach programs running on the host Mac itself. | 3 |
| Hybrid search | Running keyword (BM25) and vector search together and fusing their normalised scores; robust across exact-code and paraphrase questions. | 13 |
| ID token | The token that tells the app (not the API) who signed in: name, username, email. | 16 |
| Idempotency | Doing a job twice has the same effect as doing it once ("upsert chunks for document X at hash Y", not "append chunks"). Required with at-least-once delivery. | 15 |
| Identity provider (IdP) | The service that signs people and machines in and vouches for them with signed tokens; Keycloak in this platform. | 16 |
| Image | The frozen blueprint a container is started from: a program plus all its dependencies. | 3 |
| Image tag vs digest | A tag (`v1.104.0`) is a movable label; a digest (`@sha256:…`) is the exact, unchangeable fingerprint of one image. | 9 |
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
| justfile | A menu of named command shortcuts run with `just <recipe>` (e.g. `just check`), reused by CI. | 4 |
| JVM heap | The working memory of a Java program such as OpenSearch; typically about half the container's memory, fixed and locked in RAM. | 13 |
| JWKS (JSON Web Key Set) | The public keys an identity provider publishes (`…/protocol/openid-connect/certs`) so anyone can check its token signatures. | 16 |
| JWKS cache | The verifier's local copy of the identity provider's public keys (5 minutes here), re-fetched when a token names an unknown `kid`; avoids a Keycloak call per request. | 17 |
| JWT (JSON Web Token) | A small signed token carrying its own permissions and expiry; anyone can read it, but only the holder of the signing key can create or change it. | 12 |
| k-NN plugin / Lucene engine | OpenSearch's vector search feature, here using Lucene's HNSW implementation. | 13 |
| Key pair (public / private key) | Two matching keys: anyone can lock with the public key, only the private key unlocks. Share the public one, guard the private one. | 6 |
| Key rotation | The identity provider switching to a new signing key; APIs must pick up the new key automatically (a JWKS re-fetch on an unknown `kid`) while old tokens expire. | 17 |
| `kid` (key id) | A label in a JWT's header naming which of the identity provider's keys signed it, so the verifier knows which public key to check with. | 17 |
| KV cache | The model's working memory of everything read so far; grows with prompt and answer length and is a big part of memory use. | 7 |
| Label (metric) | A key=value pair that identifies one slice of a metric, e.g. `outcome="error"`, `job="opa"`, `service_version="0.1.0"`. Every distinct label combination is its own time series. | 20 |
| launchd | macOS's built-in service manager: starts programs at login and restarts them if they crash (agents live in `~/Library/LaunchAgents/`). | 7 |
| Least privilege | Giving each identity only the access it needs and nothing more. | 10 |
| Legal hold | An indefinite object lock with no date, applied during investigations, until someone explicitly removes it. | 14 |
| Lifecycle rule | An automatic action on objects by age, e.g. "delete temp files after 1 day" or "expire old versions after 90 days". | 14 |
| Line filter (LogQL) | A LogQL step that keeps only lines containing (`|=`), not containing (`!=`) or matching (`|~`) some text, e.g. `|= "4bf92f35…"` to find one request's lines. | 21 |
| Lineage | The recorded chain from an output (an answer) back to its inputs (chunks → document → exact file version). | 14 |
| Linter / static analysis | A tool (e.g. `ruff check`) that reads code without running it and flags likely bugs and risky patterns, each as a coded rule like `B006`. | 5 |
| Liveness / readiness | Two health questions: "is the process alive?" (restart it if not) and "can it serve traffic yet?". | 9 |
| LLM observability | Recording what an AI system was asked, what it looked up and what it answered, to debug and improve it (Langfuse here). | 22 |
| localhost / 127.0.0.1 | "This machine only": a port bound here is reachable only from your own Mac. | 3 |
| Lockfile | A file recording the exact version and hash of every package in the full dependency tree (`uv.lock`). | 2 |
| Log aggregation | Collecting every container's log lines into one central, searchable store with retention (Loki here) instead of reading files on each machine. | 21 |
| Log rotation | Keeping only the newest few log files of a limited size and deleting the oldest (here 3 × 10 MB). | 3 |
| Logging driver (Docker) | Where the Docker engine sends a container's stdout/stderr: `json-file` (default, local disk) or a network destination such as `fluentd`, which the Collector's `fluent_forward` receiver understands. | 21 |
| Login events (Keycloak) | Keycloak's record of sign-ins and failures (`LOGIN`, `LOGIN_ERROR`, …) with time, IP address and client; kept 30 days here. | 16 |
| LogQL | Loki's query language: pick streams by label (`{service_name="rag-api"}`), then filter lines (`|= "text"`) and parse them (`| json`). | 21 |
| Log–trace correlation | Putting the trace and span id in every log line, so you can jump from a trace to the exact log lines of that request and back. | 19 |
| Loki | Grafana's log store: indexes only a few labels per stream and keeps the text in compressed chunks that are scanned at query time, so it is cheap to run. | 21 |
| macOS Keychain | The Mac's built-in encrypted password store, unlocked by your login; home for personal tokens. | 6 |
| maintenance_work_mem | Postgres memory for maintenance work such as building indexes; HNSW builds are much faster when the graph fits in it. | 11 |
| Manifest (audit archive) | A small file describing one archived batch of audit events: first and last row, head hash, previous head and the segment's checksum. | 23 |
| Mapping | An OpenSearch index's schema: each field's type (`text`, `keyword`, `knn_vector` …) and analyzer. | 13 |
| Masking hook | A function in our own process that rewrites every value (tokens, keys, emails → `****`) before it is sent to Langfuse. | 22 |
| Master key | The gateway's root credential (`LITELLM_MASTER_KEY`); it can do everything, so it is for admins only. | 9 |
| Matryoshka embeddings | Embeddings trained so their first part is already a useful smaller embedding; keep the first N numbers, re-normalise, and save storage at a small quality cost. | 8 |
| Max parallel requests (concurrency limit) | How many requests one key may have in flight at once; crucial when every app shares one GPU. | 10 |
| MDM | Mobile Device Management: how company IT installs and controls software on employees' Macs (e.g. Jamf, Kandji). | 1 |
| Meaning space | The many-dimensional map an embedding model places texts on, where similar meanings sit close together. | 8 |
| Memory bandwidth | How fast data moves between memory and the GPU; each decoded token reads the model's weights, so it is the speed limit for tokens per second. | 7 |
| Merkle tree | A tree of hashes in which each parent hashes its children; allows small proofs that an entry is included in a large log. | 23 |
| Metric | A number measured over time (requests per second, latency, errors); answers "is something wrong?". | 19 |
| MFA / TOTP | Multi-factor authentication: a second proof besides the password. TOTP is the six-digit, time-based code from an authenticator app. | 16 |
| Migration | A versioned, reviewable script that changes the database structure, applied in order and recorded in the database. | 11 |
| Mixture of Experts (MoE) | A model that stores many specialist sub-networks but uses only a few per token: memory like a big model, speed like a small one. | 7 |
| Model alias (model group) | The public role name clients use, such as `qwen-fast`; LiteLLM calls it `model_name`. | 9 |
| Model inventory | A reviewed list of which exact models a platform serves: repo, revision, licence, port, role and who approved it (`infra/model-serving/models.yaml`). | 7 |
| Model revision | The exact git commit (40-character SHA) of a model repository on Hugging Face; the same name isn't always the same model. | 7 |
| Monorepo | One repository holding all services, libraries, infrastructure and docs. | 4 |
| Multi-stage build | A Dockerfile with several `FROM` stages: one with build tools makes the result, the final small image copies only that result (here the finished `.venv`). | 17 |
| Multitenancy / tenant | Serving many customers or departments from one system / one such customer, whose data must stay separate. | 12 |
| Multi-window alert | A burn-rate alert that requires both a long window (1 h or 6 h: a real trend) and a short one (5 min or 30 min: still happening) to be over the threshold, so blips don't page and alerts clear quickly after recovery. | 20 |
| Named vectors | Several vectors stored per point under different names, e.g. `dense` and `sparse`. | 12 |
| Named volume | Docker-managed storage inside the VM that survives container deletion; use it for database data. | 3 |
| Network interface | A way your machine connects to networks: Wi-Fi, Ethernet, or localhost. | 3 |
| no-new-privileges | A container security option that stops any process inside it gaining extra privileges, e.g. through setuid programs. | 9 |
| --no-verify | A git flag that skips local hooks; the reason CI must repeat the same checks. | 5 |
| Non-root container | A container whose process runs as an ordinary user (uid 10001 here), so a compromised app can't change system files or its own code. | 17 |
| Normalisation | Scaling a vector to length 1, so cosine similarity becomes a simple dot product. | 8 |
| OAuth 2.0 / OpenID Connect (OIDC) | The standards for getting tokens. OAuth 2.0 covers access ("may this app call that API?"); OIDC adds identity (who signed in) on top. | 16 |
| Object lock / retention (governance vs compliance) | Rules preventing deletion or overwrite of an object version until a retain-until date (WORM). Governance mode: privileged users can deliberately override; compliance mode: nobody can, not even admins. | 14 |
| Object metadata | Extra key-value information stored with an object (content type, source URI, sha256…). | 14 |
| Object storage / S3 API | Storing files as objects in buckets, reached over HTTP using Amazon's S3 protocol, now an industry standard spoken by AWS S3, SeaweedFS, Ceph and many more. | 14 |
| Observability | Being able to answer new questions about a running system from the outside, using its traces, metrics and logs, without shipping new code. | 19 |
| Observation (Langfuse) | One step inside a Langfuse trace, with a type: `chain`, `retriever`, `embedding`, `generation`, `tool`, `agent` … | 22 |
| Opaque token | A token that is just a random reference, not a readable JWT; only the identity provider can say what it means, via introspection. | 17 |
| Open core | A free (here MIT-licensed) core product plus paid Enterprise features; Langfuse's model. | 22 |
| OpenAI-compatible API | The same request and response format as OpenAI's API, so any tool that speaks "OpenAI" can call a local model. | 7 |
| OpenFGA | A CNCF relationship-based (ReBAC) authorisation engine modelled on Google's Zanzibar: "shared with", folder inheritance, team membership. Planned for the permission-aware RAG project. | 18 |
| OpenTelemetry | The CNCF open standard (APIs, SDKs, protocol, Collector) for producing and shipping traces, metrics and logs, supported by every major vendor. | 19 |
| OrbStack | A lightweight macOS container runtime: Linux VM + Docker engine + Compose + single-node Kubernetes. | 3 |
| OTLP | The OpenTelemetry protocol that carries all three signals: gRPC on port 4317, HTTP on 4318. | 19 |
| Package manager | A program that installs, updates and removes other software and tracks what's installed. | 1 |
| PAP (Policy Administration Point) | Where the rules are written and changed; here Git and pull requests on `policies/`. | 18 |
| Parent / child span | Spans nest: a request's server span is the parent of the steps inside it, which can have children of their own; this nesting draws the waterfall. | 19 |
| Parser (LogQL) | A LogQL step such as `| json` or `| logfmt` that turns each line's text into fields you can filter on, e.g. `| json | level="ERROR"`. | 21 |
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
| pg_dump | Postgres's logical backup tool: writes a database's structure and data to a file that `pg_restore` can load again. | 11 |
| Pipeline (Collector) | One signal's path through the Collector: receivers → processors (in order) → exporters. | 19 |
| Plaintext | Readable, unencrypted text. | 6 |
| Point | One item stored in Qdrant: an ID, one or more vectors, and a payload. Here, one chunk. | 12 |
| Policy as code | Access rules written in a real language, versioned in Git, reviewed by pull request and tested like code. | 18 |
| Policy engine | A service whose only job is to evaluate authorisation rules against facts and answer yes/no plus details; here OPA. | 18 |
| Polyrepo | One repository per service or library. | 4 |
| Pooling | How an embedding model squeezes its per-token outputs into one vector (Qwen3-Embedding uses the last token). | 8 |
| Port | A numbered "door" through which a program accepts network connections, e.g. 5432 for Postgres. | 3 |
| pre-commit (the tool) | A framework that installs and runs git hooks from one file, `.pre-commit-config.yaml`. | 5 |
| Pre-filter vs post-filter | Restricting a search inside the query (pre-filter, using the filter the policy computed) vs checking the results afterwards (post-filter); we do both, so leaks are impossible and results stay full. | 18 |
| Prefill | The first phase of generation: the model reads every prompt token in one parallel pass; limited by compute, it sets TTFT. | 7 |
| Presigned URL | A link with a built-in signature and expiry that grants temporary access to one object (or one version) without the opener needing credentials. | 14 |
| Primary key / foreign key | A row's unique ID / a column pointing to another table's row (a chunk → its document). | 11 |
| Principal | The verified caller as the code sees it after token validation: user id (`sub`), username, calling app (`azp`), groups and roles. | 17 |
| Project and API keys (Langfuse) | A Langfuse project holds traces; its public key (`pk-lf-…`) identifies it and its secret key (`sk-lf-…`) authorises writes. | 22 |
| Prompt cache | Reusing the KV cache of a prompt start sent before (e.g. the same system prompt), which makes TTFT much faster. | 7 |
| PromQL | Prometheus's query language: select series by name and labels, then compute with functions like `rate()`, `increase()`, `sum by (…)` and `histogram_quantile`. | 20 |
| Protocol mapper | A Keycloak rule that puts an extra fact into tokens, such as the `groups` claim or an extra audience. | 16 |
| Provider prefix | The part of a LiteLLM `model` before the first `/` (e.g. `openai/`): which API protocol to speak to the backend. | 9 |
| Provisioning (Grafana) | Grafana reading its data sources and dashboards from files at start-up, so they are code in Git rather than settings clicked into its database. | 20 |
| Pseudonymous id | A stable identifier (like a token's `sub`) that points to a person without naming them; the name is looked up elsewhere, under its own access rules. | 23 |
| Pull request (PR) | A request to review a branch and merge it into `main`. | 4 |
| Pull vs push (metrics) | Prometheus either fetches (scrapes) `/metrics` from a target (pull), or receives metrics sent to it, here over OTLP from the Collector (push). | 20 |
| Push / pull | Send your commits to the remote / fetch other people's commits from it. | 4 |
| pyproject.toml | The standard Python project file listing the dependency ranges you'll accept (PEP 621). | 2 |
| Quantization | Storing each of a model's numbers in fewer bits (8-bit, 4-bit): smaller and faster, at the cost of a little accuracy. | 7 |
| Query instruction | A one-sentence task description prefixed to queries (not documents) for instruction-aware embedders: `Instruct: {task}\nQuery:{query}`. | 8 |
| `rate()` / `increase()` | PromQL functions for counters: `rate` is the per-second speed over a window, `increase` the total growth over it. Both handle counter resets when a process restarts; neither can see a counter's first appearance as growth. | 20 |
| Rate limit (RPM / TPM) | How many requests per minute / tokens per minute a key may use; going over returns 429 Too Many Requests. | 10 |
| Raw zone (bronze) | The part of a data platform holding immutable original data, from which everything else can be rebuilt. | 14 |
| RBAC (role-based access control) | Deciding what each user, key or token may read or write by the role or permissions it carries. | 12 |
| Recording rule | A PromQL query Prometheus pre-computes on every evaluation and stores under a new name (e.g. `rag:search_errors:ratio_rate1h`), so dashboards and alerts stay fast and consistent. | 20 |
| Re-indexing | Re-embedding every stored document because the embedding contract changed; planned like a migration. | 8 |
| Read-only filesystem (container) | Starting a container so it can't write to its own files (`read_only: true`), with a small RAM `tmpfs` for scratch space; here code ownership by root gives the same protection because Compose can't combine it with environment-sourced secrets. | 17 |
| Realm | A separate, self-contained space in Keycloak with its own users, groups, apps and settings. `master` is only for running Keycloak itself; our apps use `rag`. | 16 |
| Realm role | A Keycloak role that says what someone may DO (`rag-user`, `rag-admin`, `rag-auditor`, `rag-ingest`). Here roles are attached to groups, never to people directly. | 16 |
| ReBAC (relationship-based access control) | Access decided by relationships between people and things ("editors of this folder", "shared with Bob"); implemented by OpenFGA and SpiceDB. | 18 |
| Recall | Of the truly closest results, the share the fast (approximate) search actually returned. | 11 |
| Receiver / processor / exporter | The Collector's building blocks: a receiver takes data in (OTLP), a processor changes it (limit, scrub, redact, label, batch), an exporter sends it out (debug, Prometheus, Tempo…). | 19 |
| Recipient | Someone (or a machine) whose public key can open a SOPS file: you, CI, a teammate. | 6 |
| Redaction | Masking a value that looks like a secret (`****`) so the record survives but the secret doesn't; the Collector's safety net for JWTs, keys and emails. | 19 |
| Refresh token | A longer-lived token an app swaps for new access tokens without signing in again; here it is one-time use and dies at logout. | 16 |
| Regal | The linter and editor language server for Rego: catches bugs and style problems in policies; part of `just policy-check`. | 18 |
| Rego | OPA's policy language: you write rules that become true or produce values, and OPA evaluates them against `input` and `data`. | 18 |
| Relational database / table / row / column | Data stored in tables; each row is a record (one chunk), each column a field (its text, its vector). | 11 |
| Remote / origin | A copy of the repository on a server (GitHub); `origin` is its default nickname. | 4 |
| Remote write | The Prometheus protocol for pushing samples into a Prometheus server (enabled with `--web.enable-remote-write-receiver`); Tempo uses it to deliver span metrics and the service graph. | 21 |
| Repository | The project's filing cabinet: all files plus their full history of changes (git). | 4 |
| Required action | Something a user must do at their next sign-in: change a temporary password, set up MFA (`CONFIGURE_TOTP`), verify an email. | 16 |
| Rescoring | After a fast search on compressed vectors, re-ranking the top candidates using the original vectors to recover accuracy. | 12 |
| Resource (OpenTelemetry) | Facts about the process sending telemetry (`service.name`, version, environment), attached to every span and metric. | 19 |
| Restart policy | The rule Docker uses to restart a container that stops or crashes (`restart: unless-stopped`). | 9 |
| Retention | How long a store keeps data before deleting it: 7 days for traces (Tempo `block_retention`) and logs (Loki `retention_period` plus `compactor.retention_enabled`). | 21 |
| Retrieve-then-rerank | The two-stage search pattern: a fast embedder finds ~50 candidates, then a slow, precise reranker picks the best few for the LLM. | 8 |
| Retry | Trying the same model again after a temporary error, before any fallback. | 10 |
| Reverse proxy | A server that sits in front of other servers, receives every request, applies rules and forwards it. | 9 |
| Revocation | Making an old secret stop working, e.g. deleting an API token. | 6 |
| RFC 3161 timestamp | A signed statement from a timestamping authority that some hash existed at a given time. | 23 |
| Role / privilege (database) | A database identity / what it's allowed to do (connect, read, write, create tables). | 11 |
| Role mapping | The link in OpenSearch's security plugin that gives a user (or backend role) the permissions of a role. | 13 |
| Rotation | Replacing a secret with a new value on a schedule, or immediately after a suspected leak. | 6 |
| Routing | Choosing which real backend (deployment) answers a request for a given model alias. | 9 |
| Routing (alerts) | Alertmanager's tree of matchers that sends each alert to a receiver: here `severity="critical"` goes to `platform-team-urgent` (page), everything else to `platform-team` (ticket). | 20 |
| Rule (Rego) | A named statement such as `allow if { ... }`, true when every line in its body is true; several rules with the same name mean OR. | 18 |
| Runbook | Step-by-step instructions linked from an alert: what it means, what to check first, likely causes, how to fix, how to close. Every alert here links one under `docs/runbooks/`. | 20 |
| S3 endpoint | The server URL to send S3 requests to (here `http://127.0.0.1:8333`), passed to tools as `--endpoint-url` / `endpoint_url`. | 14 |
| Salt key (LITELLM_SALT_KEY) | A secret LiteLLM uses to encrypt credentials it stores in its database; it must never change, or those become unreadable. | 10 |
| Sampling (head / tail) | Keeping only some traces. Head sampling decides when a request starts; tail sampling decides after seeing the whole trace (e.g. keep all errors and slow ones). | 19 |
| Scalar quantization (int8) | Storing each vector number as a 1-byte integer instead of 2–4 bytes: about 4× smaller and faster to scan. | 12 |
| Schema (database) | A named folder of tables inside a database (we use `rag`); also "the structure" of the tables. | 11 |
| Score (LLM evaluation) | A judgement attached to a trace: thumbs up/down, a 0–1 rating, or an evaluator's verdict. | 22 |
| Score normalisation | Rescaling scores from different methods to the same range (min-max: best = 1, worst = 0) before combining them. | 13 |
| Scrape | Prometheus fetching a target's `/metrics` page on a schedule (every 15 s here), optionally with a bearer token read from a secret file. | 20 |
| Search engine | A system built to find documents by their words (and now vectors) fast, with relevance ranking; e.g. OpenSearch, Elasticsearch. | 13 |
| Search pipeline | Processing steps OpenSearch applies around a search, e.g. normalising and combining scores for hybrid search (`rag-hybrid`). | 13 |
| Search-path hijacking | Tricking a privileged database function into calling an attacker's look-alike object; prevented by fixing the function's `search_path` (with `pg_temp` last). | 23 |
| Secret | Any value that grants access: a password, API key, token, private key or encryption key. | 6 |
| Secret file / /run/secrets | A secret delivered to a container as a small in-memory file, the standard Docker and Kubernetes pattern. | 6 |
| Secret scanner | A check (e.g. gitleaks, detect-private-key) that looks for keys, tokens and passwords before they are committed. | 5 |
| SecretStr | A pydantic type that prints as `**********`; the real value needs a deliberate `.get_secret_value()`. | 6 |
| `SECURITY DEFINER` | A Postgres function that runs with the rights of its owner, not its caller; lets rag-api append audit events without any rights on the table. | 23 |
| Security plugin | OpenSearch's built-in TLS, users, roles and permissions; never disable it. | 13 |
| Semantic conventions | Agreed attribute names (`http.request.method`, `gen_ai.request.model`) so every tool understands the data. | 19 |
| Semantic Versioning | MAJOR.MINOR.PATCH version numbers: breaking change → major, `feat` → minor, `fix` → patch. | 4 |
| Service account | A non-human identity tied to a confidential client, used with client credentials (e.g. `service-account-ingestion-worker`). | 16 |
| Service graph | Who-calls-whom metrics (`traces_service_graph_request_total{client, server}`) that Tempo computes from client/server spans; Grafana draws them as boxes and arrows. | 21 |
| Session / user / tags | Ways to group LLM traces: a conversation, a (pseudonymous) person, free-form labels. | 22 |
| SHA-256 | A hash function producing a 32-byte fingerprint: the same input always gives the same output, one changed bit changes it completely, and it can't be reversed or collided in practice. | 23 |
| Shadow price | An internal, notional price for something with no bill (your own GPU time), so usage can be compared and budgeted; here $2/hour ÷ tokens per second. | 10 |
| Shard / replica | The pieces an index is split into / copies of them for safety; one node uses 1 shard and 0 replicas. | 13 |
| shared_buffers | Postgres's own memory cache for table and index pages, typically about 25% of the memory it may use. | 11 |
| Shell / zsh | The program inside Terminal that reads and runs your commands; zsh is the macOS default. | 1 |
| Shift left | Moving checks earlier in the process (editor, commit) where fixing problems is cheapest. | 5 |
| Showback / chargeback | Showing each team what it used / actually billing its cost centre for it. | 10 |
| Side door | A way to read data around the access policy, for example a trace viewer showing documents the reader isn't cleared for. | 22 |
| Signal | One kind of telemetry: traces, metrics or logs. | 19 |
| Signed commit | A commit stamped with your private key so GitHub can show it as Verified (really from you). | 4 |
| Silence | A deliberate, time-limited mute of matching alerts in Alertmanager, e.g. during planned maintenance; stored so it survives restarts. | 20 |
| SLI / SLO / SLA | Service level Indicator (what you measure, e.g. the share of searches that succeed) / Objective (your internal target, 99% over 28 days) / Agreement (the contractual promise to customers, set looser than the SLO). | 20 |
| Snapshot | A point-in-time backup file of a collection. | 12 |
| SOPS | "Secrets OPerationS": encrypts the values in YAML, JSON or `.env` files while leaving the names readable. | 6 |
| Source of truth | The one authoritative store that decides what exists and who may see it; every other copy is derived from it. | 12 |
| Span | One timed step in a request: name, start, duration, status and attributes. | 19 |
| Span metrics | Request rate, errors and duration per service and span name (`traces_spanmetrics_*`), computed from traces by Tempo's metrics generator. | 21 |
| Sparse vector | A vector that's mostly zeros, stored as (position, value) pairs; used for keyword-like retrieval (SPLADE, BM25-style). | 12 |
| Speculative decoding | A small draft model guesses a few tokens ahead and the big model checks them in one pass, speeding up decoding (`--draft-model`). | 7 |
| Squash merge | Merging a PR so all its small commits become one clean commit on `main`. | 4 |
| src layout | Putting a package's code under `src/<name>/` so tests import the installed package, not the raw folder. | 4 |
| SSDLC | Secure Software Development Lifecycle: building security checks (static analysis, secret scanning) into every change. | 5 |
| SSH key | A private key that stays on your Mac and a public `.pub` key you give GitHub, to prove it's you without a password. | 4 |
| SSO session | Your sign-in at Keycloak itself. While it lasts (30 idle minutes, 10 hours at most here), other apps sign you in without asking again. | 16 |
| Staged files | The files you have `git add`-ed: exactly what the next commit will contain, and what hooks check. | 5 |
| Stemming | Reducing words to a common root ("Fridays" → "fridai") so variations of a word match. | 13 |
| Stream (Loki) | All log lines that share exactly the same set of labels; each unique label combination is a separate stream, so labels must have few values. | 21 |
| Stream (Valkey/Redis) | An append-only log of messages, each with an increasing ID (`XADD`); with consumer groups it works as a crash-safe job queue. | 15 |
| Streaming (SSE) | Sending an answer token by token as it is generated, over Server-Sent Events, instead of all at the end. | 9 |
| Structured logging | Writing logs as JSON objects instead of free text, so they can be filtered and joined by field. | 19 |
| Structured metadata (Loki) | Extra per-line key/value facts (such as OTLP attributes) that Loki stores and can search without turning them into labels, so they don't create new streams. | 21 |
| Supersede | Replace an accepted ADR with a newer ADR that points back to it; the old one is never edited. | 4 |
| Synonyms (search) | Rules treating different terms as equivalent ("wfh" = "work from home" = "remote work"), best applied at query time with `synonym_graph`. | 13 |
| Table lock | A lock on a whole table; `LOCK TABLE … IN EXCLUSIVE MODE` lets only one writer append at a time (so the chain can't fork) while readers carry on. | 23 |
| Tamper-evident vs tamper-proof | Evident: changes can't be hidden. Proof: changes are impossible. Nothing digital is tamper-proof against its own administrators; evident is the honest goal. | 23 |
| Team (LiteLLM) | A group of virtual keys sharing a budget and a model list, e.g. a department or product. | 10 |
| TEI (Text Embeddings Inference) | Hugging Face's Rust server for embedding and reranking models, with batching, API keys and metrics; runs natively with Metal on Apple Silicon. | 8 |
| Telemetry | Usage information a program sends to its makers; switched off on purpose (Qdrant here, Homebrew analytics in Step 1). | 12 |
| Telemetry (observability) | The data a system reports about itself (traces, metrics, logs) for its own operators; not to be confused with usage data sent to a vendor. | 19 |
| Term frequency (tf) | How often a query word appears in a document; more helps in BM25, with diminishing returns. | 13 |
| Tempo | Grafana's trace store: keeps every span cheaply in blocks, finds traces by id or TraceQL, and can generate metrics from them. | 21 |
| text vs keyword field | `text` is analysed for full-text search; `keyword` is stored exactly, for filters and IDs. | 13 |
| Thinking mode | Qwen models' optional hidden reasoning before the answer; better on hard questions, slower and more tokens (`enable_thinking`). | 7 |
| Throughput | How much work a server finishes per second, e.g. chunks embedded per second. | 8 |
| Time series | One metric with one exact set of labels, sampled over time, e.g. `rag_search_requests_total{outcome="ok"}`. | 20 |
| Token | The unit a model reads and writes: roughly ¾ of an English word. | 7 |
| Token filter | An analyzer step that changes the token stream: lowercase, synonyms, stemming. | 13 |
| Token introspection (RFC 7662) | Asking the identity provider "is this token still valid?" on every request: instant revocation, at the cost of a network call each time. | 17 |
| Token revocation | Cancelling a token before it expires. With local validation it only takes full effect when the (5-minute) access token expires. | 17 |
| Token validation | Proving a token is genuine and meant for you (signature, algorithm, issuer, audience, expiry, type, calling app) before believing anything in it. | 17 |
| Tokenizer | The model's dictionary for converting text to tokens and back. | 7 |
| Tokenizer (search) | The analyzer step that splits text into words (tokens); not the same as an LLM's tokenizer. | 13 |
| Tokens per second (tok/s) | How fast an answer streams once it starts; mostly set by memory bandwidth. | 7 |
| Trace | All the spans of one request, across all services, sharing one trace id. | 19 |
| Trace backend | A store that keeps traces and finds them by id or by query (Tempo here; Jaeger is another). | 21 |
| traceparent (W3C Trace Context) | The standard HTTP header that carries the trace id and parent span id to the next service. | 19 |
| TraceQL | Tempo's query language for finding traces by span facts, e.g. `{resource.service.name="rag-api" && duration > 2s}`. | 21 |
| Transitive dependency | A dependency of a dependency: a package you never chose that comes along because one you chose needs it. | 2 |
| Transparency log | A public append-only log built on a Merkle tree (Certificate Transparency, Sigstore Rekor) that lets outsiders verify entries without trusting the operator. | 23 |
| Trigger (database) | Code the database runs automatically before or after a change; here a statement trigger that refuses any change to the audit table. | 23 |
| Truncation / max sequence length | The longest text a model reads; anything beyond is cut off, silently in TEI by default (`--auto-truncate`). | 8 |
| Trunk-based development | `main` (the trunk) is always working; every change goes through a short-lived branch and a PR. | 4 |
| TTFT (time to first token) | How long you wait before the first word appears; mostly set by prefill and prompt length. | 7 |
| TTL (time to live) | An expiry time on a key; it disappears automatically afterwards. Every cache entry gets one. | 15 |
| Type checker | A tool (e.g. `mypy`) that reads type hints and checks they are used consistently, catching wrong-kind-of-value bugs before running. | 5 |
| Type hint | A label saying what kind of value a variable or function expects or returns, e.g. `def chunk(text: str) -> list[str]`. | 5 |
| Unified memory | Apple Silicon memory shared by the CPU and GPU; every GB given to the container VM is a GB the models lose. | 3 |
| uv | Astral's all-in-one Python tool: interpreters, virtual environments, locking and tool installs. | 2 |
| Valkey | The open-source (BSD), Redis-compatible in-memory store maintained under the Linux Foundation, forked from Redis in 2024 after Redis's licence change. | 15 |
| Versioning / version ID | Keeping every overwrite of an object as a separate version, each with its own ID, so nothing is silently lost. | 14 |
| Virtual environment | A private folder of packages (`.venv`) for one project, tied to one interpreter. | 2 |
| Virtual key | A per-app or per-person key issued by the gateway, with its own budget, limits and allowed models; needs a database (Step 10). | 9 |
| Virtual machine (VM) | A computer simulated inside your computer; on a Mac, containers run inside a small Linux VM. | 3 |
| Wheel | A pre-built Python package, ready to install, like flat-pack furniture. | 2 |
| Wired memory / GPU working-set limit | The share of unified memory macOS lets the GPU lock for itself (`iogpu.wired_limit_mb`); large models need it big enough. | 7 |
| Workspace (uv) | Several Python packages in one repository sharing one `uv.lock` and one `.venv`. | 4 |
| WORM (write once, read many) | Storage where data can be written once and then never changed or deleted until its retention ends; what object lock provides. | 14 |
| `WWW-Authenticate` | The response header on a 401 telling the client a bearer token is required, or (with `error="invalid_token"`) that the one sent was not accepted. | 17 |
| Zanzibar | Google's paper and system for relationship-based authorisation at global scale; the model behind OpenFGA and SpiceDB. | 18 |
