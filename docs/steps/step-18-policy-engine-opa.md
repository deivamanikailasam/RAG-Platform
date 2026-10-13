# Step 18 · Policy engine: OPA (with OpenFGA in view)

*Step 18 of 38 · Phase D · Identity & policy*

## At a glance

| | |
|---|---|
| **Goal** | Move every authorisation rule out of the API's code into a policy engine. The API only asks: "may this person do this action, and which documents may they see?" Open Policy Agent (OPA) answers from rules written in Rego, kept in Git, tested like code, and logged on every decision. We add the RAG rule that groups alone can't express: classification clearance, with caps that override grants. |
| **Time** | About 2 hours. |
| **You'll end up with** | `policies/` in the repo: the authorisation policy, its data (role and clearance mappings) and 21 policy tests (98% coverage), linted by Regal; `opa` in Compose (1.21.x): read-only policies, its own API locked down (token required, no policy uploads), every decision logged as JSON; rag-api changed from "has role X?" to "ask the policy": endpoints name an action, OPA decides, the API obeys and fails closed (503) if OPA is down; permission-aware search done properly: OPA computes the filter, Postgres applies it, OPA re-checks the results; 26 Python tests for the API (4 of them against a real OPA); ADR-0018. |
| **New words** | Authorisation policy, policy engine, policy as code, PEP / PDP / PAP, Rego, rule, `default`, `input` vs `data`, deny-by-default, fail open vs fail closed, ABAC, ReBAC, clearance, cap (deny overrides), partial evaluation / data filtering, pre-filter vs post-filter, decision log, Regal, OpenFGA, Zanzibar. |

## The big idea

> **ANALOGY · THE RULEBOOK AT THE FRONT DESK**
> So far each door guard (API endpoint) carried their own little rule list: "admins only", "staff only". With ten
> services that means ten slightly different lists, and nobody can answer "who can see salary documents?" without
> reading all the code.
>
> A policy engine is a single rulebook office. Guards don't decide; they phone the office with three facts: who is
> asking (from the badge), what they want to do, and which thing. The office looks up the rulebook and answers
> yes / no, and here's why. It writes every answer in a ledger.
>
> The rulebook itself is written down, reviewed and tested. Changing a rule means changing the book, not
> retraining every guard.

```text
          The API asks one question: "may THIS principal do THIS action on THIS resource?"

   Caller                    rag-api                    input                       OPA
   alice's token  ─request─► ENFORCES (PEP)  ─────────────────────────────────► DECIDES (PDP)
                             names the action, obeys  ◄──────── decision ─────── policy (Rego) + data (JSON)
                             the answer, never decides                           ~1 ms, no network calls
                                                                                       ▲ loaded read-only
   input = facts, not wishes        Decision log                                  policies/ (Git)
   principal from the verified      who · action · result · reasons               authz.rego · data.json
   token + action + documents       → audit trail (Steps 21, 23)                  authz_test.rego
```

*Figure 57. Separation of duties. rag-api enforces (Policy Enforcement Point); OPA decides (Policy Decision Point)
from policies and data kept in Git; every decision is logged for the audit trail.*

## What we're doing

1. Write the policy in Rego, with its data in JSON, and tests for every rule. Lint it with Regal.
2. Lock down OPA's own API with a second, tiny policy.
3. Run OPA in Compose with read-only policies and decision logging.
4. Change rag-api to ask OPA: actions instead of role checks; a pre-filter in SQL from OPA's answer, and a
   post-check of the results.
5. Test the wiring, including against a real OPA, then try it live.
6. Record ADR-0018.

## Why we're doing this

> **WHY THIS MATTERS**
> Authorisation rules in RAG grow fast:
>
> - "HR documents for HR."
> - "Restricted documents only with restricted clearance."
> - "Contractors never above internal, whatever their team."
> - "Auditors can read logs but not documents."
> - "This customer's data only for this customer" (multi-tenancy).
>
> Written as `if` statements, they end up scattered across services, inconsistent, untested and impossible to
> review. A policy engine gives one place, one language, one test suite and one log for every access decision.
> Auditors and security teams can read and approve it, and the same policy serves every service.

| Need | How this step meets it |
|---|---|
| One set of rules for all services | OPA as the shared decision point |
| Rules reviewable by security | Policy as code in Git, changed by pull request |
| Rules proven correct | `opa test` with coverage threshold, Regal lint, in `just check` |
| Sensitivity, not just teams | Clearance from groups; caps (contractors) always win |
| Mappings change without code | `data.json`: which role an action needs, what clearance a group gives |
| Search stays fast and safe | Policy-computed pre-filter + policy post-check |
| If the policy engine fails | Fail closed: 503, never "allow" |
| Who was allowed what, and why | Decision log with reasons (feeds Steps 21 and 23) |

> **IN A COMPANY**
> "Externalised authorisation" is standard in regulated companies. Common audit questions:
>
> - Show me the access rules.
> - Who approved this change, and when?
> - Prove the rules work.
> - Show me the decision for this request last Tuesday.
>
> Git history answers the first two, policy tests the third, decision logs the fourth. OPA is a CNCF graduated
> project, used for Kubernetes admission control, API authorisation and infrastructure checks, so security teams
> often know it already.

## Key ideas

| Term | Plain-English meaning |
|---|---|
| **Policy as code** | Access rules written in a real language, versioned in Git, reviewed and tested like code. |
| **PEP / PDP / PAP** | Enforcement Point (the API, which obeys) / Decision Point (OPA, which decides) / Administration Point (Git, where rules are written). |
| **Rego** | OPA's language. You write rules that are true or produce values; OPA evaluates them against facts. |
| **`input` vs `data`** | `input`: facts about this request (who, what action, which documents). `data`: standing facts (mappings, lists) loaded with the policy. |
| **Deny by default** | Nothing is allowed unless a rule explicitly allows it (`default allow := false`). |
| **Fail closed vs fail open** | When something breaks or is missing: deny (closed) or allow (open). Security always wants closed. |
| **ABAC** | Attribute-based access control: rules on facts (classification, clearance, department) rather than just roles. |
| **Clearance / cap** | The highest classification a person may read / a limit that overrides any grant. |
| **Pre-filter / post-filter** | Restrict during the search (in the query) / check after the search (on the results). We do both. |
| **Decision log** | OPA's record of each decision: input, result, time, decision id. |
| **ReBAC / Zanzibar / OpenFGA** | Relationship-based access ("editors of this folder"), from Google's Zanzibar paper; OpenFGA and SpiceDB implement it. |

> **IN PLAIN ENGLISH · THE OTHER NEW WORDS**
>
> - **Authorisation policy**: the written rules that say who may do what and see which things.
> - **Policy engine**: a program (here OPA) whose only job is to evaluate those rules and answer yes/no plus details.
> - **Rule** (Rego): a named statement such as `allow` that becomes true, or produces a value, when every line in
>   its body is true. Several rules with the same name mean OR.
> - **`default`** (Rego): the value a rule has when no rule body matches, e.g. `default allow := false`.
> - **Partial evaluation / data filtering**: OPA evaluating a policy with some facts unknown, and turning what's left
>   into a filter (even a SQL `WHERE` clause) that a database can apply.
> - **Regal**: the linter (style and bug checker) and editor language server for Rego.

### Three ways to model access

```text
   RBAC · roles                     ABAC · attributes                 ReBAC · relationships
   EXAMPLE RULE                     EXAMPLE RULE                      EXAMPLE RULE
   "admins may manage               "confidential docs need           "editors of a folder can
    collections"                     confidential clearance"           read every doc inside"
   TOOLS                            TOOLS                             TOOLS
   Keycloak roles (Step 16)         OPA · Cedar · Cerbos (this step)  OpenFGA · SpiceDB (Zanzibar model)
   + simple, auditable              + rich rules, any fact            + sharing, hierarchies
   - coarse; role explosion         - you must supply the facts       - another store to sync

   Real systems combine them: roles for actions, attributes for sensitivity, relationships for sharing.
```

*Figure 58. RBAC, ABAC and ReBAC. Roles answer what you may do; attributes answer how sensitive something is;
relationships answer who it was shared with. Real systems combine them.*

> **WHY OPA NOW, AND OPENFGA LATER?**
> Our current rules are about attributes: groups, classification and caps. That is OPA's sweet spot, and it needs no
> extra database: the facts arrive in the token and the document rows.
>
> OpenFGA (a CNCF project; v1.19 in August 2026) shines for relationships: "Bob shared this document with Carol",
> "everyone who can edit a folder can read its files", "members of team X inherit access to project Y". Those need
> a relationship store that stays in sync with your documents. We'll bring OpenFGA in for the permission-aware RAG
> project where sharing and folder inheritance appear.
>
> Many companies run both: OPA for policy, OpenFGA for relationships, with OPA able to ask OpenFGA.

### Filtering a search without leaking

```text
   1 · OPA decision               2 · pre-filter in the query                top-k candidates      3 · post-check
   groups: all-staff, eng…  ───►  WHERE classification = ANY(classes)  ───►  e.g. 5 documents ───► readable_ids
   classes: public, internal      AND (public OR acl && groups)                                    answer only what passed
                                                                     mismatch → dropped + error log

   Why not ask OPA about every chunk? A vector search may look at thousands of chunks. Filtering after retrieval
   returns too few results (or none) and leaks timing; one call per chunk is too slow. So: the policy computes a
   FILTER, the database applies it, the policy re-checks the few results.
```

*Figure 59. How search stays fast and safe. OPA computes a filter, the database applies it inside the vector query,
and OPA re-checks the few results. Any disagreement drops the document and logs an error.*

> **WATCH OUT · THE RAG-SPECIFIC TRAP: FILTER AFTER RETRIEVAL**
> The naive approach is: search everything, then remove what the user can't see. That fails in three ways:
>
> - **Too few results**: if the top 5 hits are all restricted, the user gets nothing, even though readable answers
>   exist further down.
> - **Timing leaks**: slower answers can hint that hidden documents matched.
> - **Accidents**: a later code change "temporarily" skips the filter.
>
> The correct pattern is pre-filter in the query (the filter comes from the policy) plus a post-check of the few
> results (defence in depth). OPA can also compile a policy into a SQL `WHERE` clause itself (its data-filtering
> feature), which removes even the small duplication in our query. We'll look at it when the rules grow.

## How to do it

On your Mac, in the project folder, on a feature branch:

```bash
cd ~/dev/rag-platform
git switch -c feat/opa-policy
brew install opa regal          # also add both to the Brewfile
opa version | head -1           # Version: 1.21.x
```

Both tools are added to [`bootstrap/Brewfile`](../../bootstrap/Brewfile):

```ruby
# ---- Policy as code (Step 18) ----
brew "opa"                  # Open Policy Agent: evaluate and test Rego policies
brew "regal"                # Rego linter and language server (editor support)
```

### 1 · The policy's data: mappings, not logic

Which role an action needs, and what clearance a group gives, are facts that change more often than rules. They
live in [`policies/rag/authz/data.json`](../../policies/rag/authz/data.json), loaded as `data.rag.authz.*` (OPA maps
the folder path to the data path). Adding a new group's clearance is a one-line, reviewable change that needs no
new code.

```json
{
    "action_roles": {
        "search": "rag-user",
        "admin:ping": "rag-admin",
        "collections:manage": "rag-admin",
        "audit:read": "rag-auditor",
        "documents:ingest": "rag-ingest"
    },
    "group_clearance": {
        "all-staff": "internal",
        "engineering": "internal",
        "hr": "confidential",
        "executives": "restricted",
        "platform-admins": "internal",
        "auditors": "internal"
    },
    "capped_groups": {
        "contractors": "internal"
    }
}
```

The role names are the Step 16 realm roles and the group names are the Step 16 groups (the same values as the
documents' `acl_groups`, Step 11). `tests/test_policy_engine.py` checks that the two stay in sync.

### 2 · The policy

[`policies/rag/authz/authz.rego`](../../policies/rag/authz/authz.rego) is the whole rulebook. In short:

```rego
package rag.authz

# Classification levels, lowest to highest (same values as the documents table, Step 11).
levels := {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}

# Missing fields become empty values, never "undefined" ...
principal := object.get(input, "principal", {})
roles := object.get(principal, "roles", [])
groups := object.get(principal, "groups", [])

# Every reason to refuse. The request is allowed only if this set is empty (deny by default).
reasons contains msg if { ...unknown action... }
reasons contains msg if { ...missing required role... }

default allow := false
allow if {
	data.rag.authz.action_roles[input.action] # a known action, AND
	count(reasons) == 0 # no reason to refuse
}

default clearance := -1                        # no known groups: nothing at all (fail closed)
clearance := max({lvl | some g in groups; lvl := levels[data.rag.authz.group_clearance[g]]})
effective_clearance := min({clearance} | caps) if { ...caps from capped_groups... } else := clearance
classifications := sort([c | some c, lvl in levels; lvl <= effective_clearance])

can_read(doc) if { doc.classification in classifications; doc.classification == "public" }
can_read(doc) if { doc.classification in classifications; some g in doc.acl_groups; g in groups }

decision := {"allow": allow, "reasons": ..., "filter": {"groups": ..., "classifications": classifications}}
readable_ids contains doc.id if { some doc in input.documents; can_read(doc) }
```

> **IN PLAIN ENGLISH · READING REGO, LINE BY LINE**
>
> - A rule like `allow if { … }` is true when every line inside the braces is true. Several rules with the same
>   name mean OR.
> - `default allow := false`: if no rule makes `allow` true, it's false. That's deny by default.
> - `reasons contains msg if { … }` builds a set of reasons to refuse. `allow` additionally requires the set to be
>   empty, so any single reason blocks the request and is reported back.
> - `clearance` takes the highest level any of your groups grants. `effective_clearance` then applies caps, the
>   lowest of which always wins. A contractor in `executives` stays at `internal`: deny overrides allow.
> - `classifications` turns the clearance into the list the database filter needs.
> - `can_read(doc)`: classification allowed and (the document is public or it shares a group with you).
> - `decision` and `readable_ids` are the two entrypoints services call (marked `# entrypoint: true` in their
>   METADATA). Everything else is internal.

> **WATCH OUT · THE BUG THE TESTS CAUGHT: UNDEFINED MEANS SKIPPED**
> The first version used `input.principal.roles` directly. A request with no principal at all was then allowed:
>
> - `input.principal.roles` was undefined, so the "missing role" reason couldn't be computed.
> - No reason to refuse meant `allow` was true. That's fail open.
>
> The fix is the three `object.get(…)` lines at the top, which turn missing fields into empty values. This is the
> most common Rego mistake. It is caught by `test_missing_principal_denied` below, which is exactly why policies
> need tests.

### 3 · Test the policy like code

[`policies/rag/authz/authz_test.rego`](../../policies/rag/authz/authz_test.rego) defines six test people (alice in
engineering, bob in hr, carol in executives, dave the admin, the ingestion worker with no groups, and zoe the
contractor who is also in executives) and the four Step 11 documents (remote work: internal for all-staff; salary
bands: confidential for hr; exec offsite: restricted for executives; press release: public). Then 16 tests, each one
access question with its expected answer:

| Group | Tests |
|---|---|
| Actions | user may search; user may not use admin (and the reason says which role is missing); admin role comes through; machine may ingest but not search; unknown action denied; missing action denied; missing principal denied |
| Search filter | alice's filter is `["all-staff","engineering"]` + `["internal","public"]`; clearance follows groups (bob up to confidential, carol up to restricted); cap beats grant (zoe only internal); no groups means nothing |
| Per document | alice reads {1, 5}; bob reads {1, 3, 5}; carol reads {1, 4, 5} (not salary bands: wrong group); the contractor in executives still reads only {1, 5}; a group match is not enough without clearance (a confidential document shared with all-staff stays hidden from alice) |

```rego
test_missing_principal_denied if not authz.allow with input as {"action": "search"}

test_cap_beats_grant if {
	authz.classifications == ["internal", "public"] with input as {"principal": contractor}
}
```

`with input as …` runs a rule as if that request had arrived. Each test is one access question with its expected
answer: a readable specification a security reviewer can check line by line.

### 4 · Protect OPA itself

By default, OPA's REST API lets anyone who can reach it upload new policies. An attacker inside the network could
then simply install `allow := true`. A second, tiny policy,
[`policies/system/authz/authz.rego`](../../policies/system/authz/authz.rego) (`package system.authz`), protects OPA's
own API: only rag-api's token may ask questions, only under `rag/authz`, and nobody may change policies over the
API.

```rego
package system.authz

default allow := false

# The health endpoint is open (no secrets in it) so probes can use it.
allow if {
	input.method == "GET"
	input.path == ["health"]
}

# Decisions: POST to /v1/data/rag/authz/..., with the shared token.
allow if {
	input.identity == opa.runtime().env.OPA_API_TOKEN
	input.method == "POST"
	array.slice(input.path, 0, 4) == ["v1", "data", "rag", "authz"]
}
```

Its five tests ([`policies/system/authz/authz_test.rego`](../../policies/system/authz/authz_test.rego)) replace
`opa.runtime` with a fake environment and prove: rag-api may ask for decisions, a wrong token is refused, policy
uploads are refused, other data (`/v1/data`) is hidden, and `/health` is open.

Regal (the Rego linter) can't see `data.json`, so [`.regal/config.yaml`](../../.regal/config.yaml) tells it those
references are expected:

```yaml
rules:
  imports:
    unresolved-reference:
      level: error
      except-paths:
        - data.rag.authz.action_roles      # these come from policies/rag/authz/data.json
        - data.rag.authz.group_clearance
        - data.rag.authz.capped_groups
```

A new recipe in the [`justfile`](../../justfile) runs every policy gate, and `just check` now calls it:

```make
# Policies: formatted, compiled strictly, linted, tested with >= 90% coverage (Step 18)
policy-check:
    opa fmt --list --fail policies
    opa check --strict policies
    regal lint policies
    opa test policies --coverage --threshold 90 > /dev/null
    opa test policies
```

```bash
just policy-check
```

> **WHAT YOU SHOULD SEE**
>
> - Regal: `No violations found`.
> - `opa test`: `PASS: 21/21` (16 tests for `rag.authz`, 5 for `system.authz`).
> - Coverage: 98%, so the 90% threshold passes.
>
> Run `opa test policies --coverage --format=json` to see which lines no test touches.

### 5 · Run OPA

OPA takes one token (for rag-api), shared through the usual secrets. Generate one and add it to the encrypted file:

```bash
openssl rand -base64 48 | tr -d '/+=\n' | cut -c1-40; echo
just secrets-edit                 # add: OPA_API_TOKEN=<value>
```

(New setups get it automatically: [`scripts/new-dev-secrets.sh`](../../scripts/new-dev-secrets.sh) now generates
`OPA_API_TOKEN`, and [`.env.example`](../../.env.example) lists it.)

Pin the current image (`openpolicyagent/opa:1.21.1-static` at the time of writing) by digest, as always. The
service in [`infra/compose/compose.yaml`](../../infra/compose/compose.yaml):

```yaml
  opa:
    image: openpolicyagent/opa:1.21.1-static@sha256:4675ab04ad1627f74741d2d9c5142698c79e18b7b09f192587d31d6dba20838e
    command:
      - run
      - --server
      - --addr=0.0.0.0:8181
      - --authentication=token                # read "Authorization: Bearer ..." as the caller's identity
      - --authorization=basic                 # ...and let system.authz decide what that identity may do
      - --bundle
      - /policies
      - --ignore=*_test.rego                  # tests stay out of the running server
      - --watch                               # dev: reload when you save a policy file
      - --log-format=json
      - --set=decision_logs.console=true      # every decision to stdout, as JSON
    environment:
      OPA_API_TOKEN: ${OPA_API_TOKEN}         # read by system.authz via opa.runtime()
    volumes:
      - ../../policies:/policies:ro           # policies come from Git, read-only
    ports:
      - "127.0.0.1:8181:8181"
    user: "65532:65532"                       # OPA warns when run as root; it doesn't need it
    read_only: true
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    restart: unless-stopped
    deploy:
      resources:
        limits: { memory: 256m, cpus: "0.5" }
```

> **IN PLAIN ENGLISH · A FEW CHOICES EXPLAINED**
>
> - **No healthcheck**: the `-static` image contains only the `opa` program (no shell, no curl), and OPA has no
>   built-in health command. rag-api protects itself instead: if OPA doesn't answer, requests get 503. Prometheus
>   will watch OPA's `/health` and `/metrics` from Step 20.
> - **The token is an environment variable, not a file like elsewhere.** The policy reads it through
>   `opa.runtime()`, and Rego can't read arbitrary files. The exposure is limited: the variable is only inside this
>   container, and the port is bound to `127.0.0.1`.
> - **`--watch`**: convenient while you edit policies. In production, policies come as signed bundles from a bundle
>   server, and the container never mounts your working folder (Phase G).

Start it and try the three things that matter: a decision, no token, and a policy upload:

```bash
just up && just ps
T=$(sops exec-env secrets/dev.enc.env 'printf %s "$OPA_API_TOKEN"')   # only for this manual test
curl -s -H "Authorization: Bearer $T" -X POST localhost:8181/v1/data/rag/authz/decision \
  -d '{"input":{"principal":{"groups":["all-staff","hr"],"roles":["rag-user"]},"action":"search"}}' | jq .result
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8181/v1/data/rag/authz/decision -d '{}'   # 401: no token
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $T" -X PUT localhost:8181/v1/policies/x \
  --data-binary 'package rag.authz
allow := true'                                                                                         # 401: uploads refused
unset T
docker compose -f infra/compose/compose.yaml logs --no-log-prefix opa | grep decision_id | tail -1 | jq '{path, input, result}'
```

> **WHAT YOU SHOULD SEE**
>
> - Bob's decision: `allow: true`, filter groups `["all-staff","hr"]`, classifications
>   `["confidential","internal","public"]`.
> - No token: 401.
> - Policy upload: 401, "request rejected by administrative policy".
> - Decision log: the last line shows the input, the result and a `decision_id`. That's the audit evidence for this
>   decision.

### 6 · rag-api asks the policy

A small client, [`services/rag-api/src/rag_api/policy.py`](../../services/rag-api/src/rag_api/policy.py), turns OPA's
JSON into typed results and treats anything unexpected as an error, never as "yes":

- `PolicyUnavailable`: OPA could not be reached or answered nonsense. Maps to HTTP 503: we never guess.
- `SearchFilter`, `Decision`, `DocumentRef`: frozen dataclasses for the filter, the decision (allow, reasons,
  filter) and a document's access facts (id, classification, ACL groups).
- `PolicyEngine`: the protocol (`decide`, `readable`) the API depends on, so tests can swap in a fake.
- `_principal_input()`: only facts from the **verified** token go to the policy (sub, username, client id, groups,
  roles), never anything the caller sent.
- `OpaClient`: an `httpx` client with the bearer token and a 2-second timeout. `_query()` turns any HTTP error,
  non-JSON body or missing `result` (an undefined result means the policy isn't loaded) into `PolicyUnavailable`.
  `decide()` allows only on a literal `true`; `readable()` skips the call for an empty list and insists on a list
  of ids.

[`settings.py`](../../services/rag-api/src/rag_api/settings.py) gains two settings:

```python
    opa_url: str = "http://opa:8181"
    opa_token: SecretStr                     # file /run/secrets/rag_api_opa_token
```

The query in [`search.py`](../../services/rag-api/src/rag_api/search.py) now takes both parts of the filter from the
policy and returns each candidate's access facts, so the policy can re-check them:

```sql
-- The filter VALUES come from the policy (OPA); this query only applies them.
SELECT d.id, d.title, d.classification, d.acl_groups,
       round((1 - (c.embedding <=> %(q)s))::numeric, 3)::float AS score
FROM rag.chunks c JOIN rag.documents d ON d.id = c.document_id
WHERE d.deleted_at IS NULL
  AND d.classification = ANY(%(classifications)s)
  AND (d.classification = 'public' OR d.acl_groups && %(groups)s)
ORDER BY c.embedding <=> %(q)s
LIMIT %(k)s
```

The backend returns `Candidate`s (a `DocumentRef` for the policy plus the `Hit` the caller sees). It still fails
closed: no classifications means no documents and no database call.

In [`main.py`](../../services/rag-api/src/rag_api/main.py), `require_role(...)` from Step 17 becomes
`authorize("action")`, and no role names remain in the API:

```python
def authorize(action: str) -> Callable[[Principal, PolicyEngine], Authorized]:
    """The API names the ACTION; the policy decides. No role names or rules live in this code."""

    def check(principal = Depends(current_principal), policy = Depends(get_policy)) -> Authorized:
        try:
            decision = policy.decide(principal, action)
        except PolicyUnavailable as e:
            log.error("policy engine unavailable: %s", e)  # fail closed: no decision, no access
            raise HTTPException(503, "Policy engine unavailable") from e
        if not decision.allow:
            log.warning("forbidden: sub=%s action=%s reasons=%s", ...)
            raise HTTPException(403, "; ".join(decision.reasons) or "Forbidden")
        return Authorized(principal, decision)

    return check
```

The search endpoint then does both halves of Figure 59:

1. **Pre-filter** inside the database query, using the filter the policy computed (fast).
2. **Post-check** every candidate with the policy's full rule (`readable_ids`). If the two ever disagree, the
   document is dropped and logged as `query/policy mismatch`: that's a bug in the query, never a leak. If OPA is
   unreachable at this point, the answer is again 503.

`/v1/admin/ping` uses `authorize("admin:ping")`.

> **TIP · ACTIONS, NOT ROLES, IN CODE**
> Endpoints now say what they do (`"search"`, `"admin:ping"`), never who may do it. When the business decides
> auditors may also search, you change one line of `data.json`, through a reviewed pull request, and every service
> follows. No code change, no redeploy of rag-api.

Give rag-api the token and make it wait for OPA (in `compose.yaml`):

```yaml
  rag-api:
    environment:
      # ...Step 17 settings, plus:
      RAG_API_OPA_URL: http://opa:8181
    secrets:
      - rag_api_gateway_key
      - rag_api_db_password
      - rag_api_opa_token                     # -> /run/secrets/rag_api_opa_token
    depends_on:
      opa: { condition: service_started }     # (Step 17 dependencies stay)

secrets:
  rag_api_opa_token: { environment: OPA_API_TOKEN }
```

### 7 · Test the wiring

The Step 17 tests move their test doubles into a shared
[`services/rag-api/tests/conftest.py`](../../services/rag-api/tests/conftest.py): the fake identity provider
(`FakeIdP`, which owns a signing key, mints tokens and doubles as the JWKS client), a fake search backend
(`FakeSearch`, fixed candidates, records what it was asked) and a fake policy (`FakePolicy`) whose answers each test
sets explicitly: allow or not, reasons, which ids are readable, or "down".

- [`test_auth.py`](../../services/rag-api/tests/test_auth.py) now uses the shared fixtures and keeps only
  authentication: the happy path, small clock skew, the 13 bad tokens and the missing token (17 tests).
  Authorisation moved to the policy.
- [`test_policy.py`](../../services/rag-api/tests/test_policy.py) checks that the API asks, obeys, fails closed and
  post-checks (5 tests): the policy gets facts from the token only (a sneaky `"groups": ["executives"]` in the body
  is ignored); search applies the policy filter and tags the user; a deny gives 403 with the reason; policy down
  gives 503, not access; the post-check drops a leaked restricted document.
- [`test_opa_live.py`](../../services/rag-api/tests/test_opa_live.py), the most valuable test of all: the real
  policy in a real OPA, through the real client. It starts OPA on a free port with a throwaway token and is skipped
  automatically on machines without `opa` (4 tests: alice's narrow filter, the admin action denied with its
  reason, who reads what including the contractor cap, and a wrong token is an error, not a yes).

```bash
just check                # now: ruff, mypy, policy-check and pytest
just api-up               # rebuild rag-api with the policy client
```

> **WHAT YOU SHOULD SEE**
> pytest: 26 passed in `services/rag-api/tests/test_auth.py`, `test_policy.py` and `test_opa_live.py`:
>
> - 17 authentication tests (as in Step 17)
> - 5 wiring tests
> - 4 live-OPA tests
>
> mypy: no issues in strict mode. If the live tests show `skipped`, `opa` isn't on your PATH; run
> `brew install opa`.

### 8 · Try it live

Run `just api-demo` (from Step 17) as alice, then as bob and carol:

| Person | Clearance from groups | Search returns |
|---|---|---|
| alice (engineering) | internal | Remote work policy, Parking |
| bob (hr) | confidential | …plus Salary bands 2026 |
| carol (executives) | restricted | …plus Exec offsite (not salary bands: wrong group) |

Now test a cap without touching any code:

1. In Keycloak, create a group `contractors` and add carol to it.
2. Sign in again as carol and search.
3. The exec document is gone, because her clearance is capped at internal. The decision log shows
   `classifications: ["internal", "public"]`.
4. Remove her from `contractors` again.

Then change the policy data:

1. Edit `data.json` so `admin:ping` requires `rag-auditor`.
2. Save. OPA reloads (`--watch`).
3. erin now gets 200 on `/v1/admin/ping` and dave gets 403 with the reason.
4. Revert the change.

That's an access change made, tested and logged without touching the API.

### 9 · Record the decision

```bash
just adr "Use OPA as the policy decision point"
```

[`docs/adr/0018-use-opa-as-the-policy-decision-point.md`](../adr/0018-use-opa-as-the-policy-decision-point.md)
records the decision: OPA 1.21.x (digest-pinned) as the Policy Decision Point; policies and mappings in `policies/`
changed by PR and checked by `just policy-check`; the two entrypoints; deny by default with missing input treated
as empty; clearance capped by `capped_groups`; OPA's API protected by `system.authz`; decisions logged; services
that name actions, fail closed and pre-filter / post-check. Alternatives: rules in service code, OpenFGA / SpiceDB,
Cedar, Cerbos, Keycloak Authorization Services. Revisit when sharing or folder inheritance appears (add OpenFGA),
rules need SQL compilation, or policies must ship as signed bundles.

```bash
git add -A
git commit -m "feat(policy): OPA decides access; rag-api enforces with pre-filter and post-check"
git push -u origin feat/opa-policy
gh pr create --fill && gh pr merge --squash --delete-branch
git switch main && git pull
```

## Benefits

- One source of truth for "who may do what and see which documents", shared by every service.
- Readable, reviewable, tested rules: 21 policy tests are an executable access specification.
- Richer RAG security: classification clearance and caps, not just group overlap.
- Changes without code: mappings live in `data.json`; services never change for access tweaks.
- Search that is fast and safe: pre-filter in the vector query, post-check of results.
- Fail closed everywhere, in the policy (undefined is never allow) and in the API (OPA down means 503).
- Audit evidence: every decision with input, result and reasons.

## Drawbacks and risks

- Another critical service: if OPA is down, the API is down (by design). Run several replicas in production.
- Rego takes learning, especially undefined values and rule merging. Tests and Regal are your safety net.
- The SQL filter mirrors the policy: if someone changes one but not the other, the post-check catches leaks but
  users may get fewer results. Keep the live tests.
- Decision logs contain personal data (user ids, groups). Treat them as sensitive: retention, access control,
  masking (Step 23).
- Latency adds up: two short calls per search (~1–2 ms locally). Fine here; batch or cache only if measured.
- Not for relationships: "shared with me" and folder inheritance need ReBAC (OpenFGA).

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| OPA (our choice) | General policy engine, Rego, CNCF graduated | Attribute rules; one engine for APIs, Kubernetes and CI |
| OpenFGA | Zanzibar-style relationship engine (CNCF) | Sharing, folders, teams, inheritance |
| SpiceDB | Zanzibar-style, strong consistency options | Large-scale ReBAC with strict consistency needs |
| Cedar / Amazon Verified Permissions | AWS's analysable policy language | AWS-centric, want formal analysis of policies |
| Cerbos | Policy engine with YAML policies | Simpler app-level rules, non-Rego teams |
| Casbin | Library inside the app | Small single-service apps |
| Keycloak Authorization Services | Policies inside the identity server | Few apps, tightly tied to Keycloak |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Classification, clearance, department, tenant rules | OPA (ABAC), this step |
| "Share this document with Bob", folder inheritance | OpenFGA / SpiceDB (ReBAC), alongside OPA |
| Very large result sets to filter | Policy-computed pre-filter, or OPA data filtering compiled to SQL |
| Strict audit / regulated industry | Decision logs shipped to tamper-evident storage (Step 23) |
| Many services in different languages | OPA as a sidecar or central service, called over HTTP |
| Kubernetes admission rules (later) | OPA Gatekeeper, same language, same skills |

## Common mistakes

- **Fail open on undefined**: a rule that silently doesn't fire means "allow". Always `default allow := false` and
  `object.get` for inputs.
- **Trusting input the caller controls**: the policy must receive facts from the verified token, never from the
  request body.
- **Leaving OPA's API open**, so anyone can PUT a new policy. Use `system.authz`, as here.
- **Filtering only after retrieval**: empty answers, timing leaks, fragile code.
- **Calling OPA per chunk or per vector**: too slow; compute a filter once.
- **Untested policies**, or tests that only check the happy path.
- **Putting mappings in code**: group-to-clearance tables belong in data, so they can change safely.
- **Treating an OPA error as "no restriction"**: errors must deny (503).

## Done when

- [ ] `policies/` contains the `rag.authz` and `system.authz` policies, `data.json` and tests; `just policy-check`
      passes (Regal clean, 21/21, coverage ≥ 90%)
- [ ] `opa` runs in Compose as a non-root user with read-only policies; requests without the token and policy
      uploads get 401
- [ ] Decision logs appear as JSON in `docker compose logs opa`
- [ ] rag-api has no role names in code; `just check` shows 26 passed (live-OPA tests not skipped)
- [ ] alice, bob and carol see different documents according to clearance; adding carol to `contractors` hides the
      exec document
- [ ] Stopping OPA makes rag-api answer 503, never data
- [ ] ADR-0018 is merged through a PR

## Recap

> **RECAP**
> Access decisions now come from a policy engine:
>
> - OPA evaluates tested, version-controlled Rego rules against facts from the verified token and the documents.
> - It answers "may they, and what may they see?", and logs every answer.
> - rag-api only enforces. It pre-filters the vector search with the policy's filter, re-checks the results, and
>   fails closed when OPA is unavailable.
> - Clearance and caps now protect sensitive documents beyond simple group overlap.
>
> This completes Phase D: who you are (Keycloak), proving it (JWT checks) and what you may do (OPA). Phase E makes
> the platform observable, starting with the OpenTelemetry Collector in Step 19.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `policies/rag/authz/data.json` | The mappings: which role each action needs, what clearance each group gives, which groups cap clearance. |
| `policies/rag/authz/authz.rego` | The authorisation policy: deny by default, reasons to refuse, clearance with caps, `can_read`, and the `decision` / `readable_ids` entrypoints. |
| `policies/rag/authz/authz_test.rego` | 16 policy tests: actions, the search filter, clearance and caps, per-document reads. |
| `policies/system/authz/authz.rego` | Protects OPA's own API: `/health` open, decisions only under `rag/authz` with the token, nothing else (no uploads). |
| `policies/system/authz/authz_test.rego` | 5 tests for the API guard, with a fake `opa.runtime()` environment. |
| `.regal/config.yaml` | Tells Regal that `data.rag.authz.*` references come from `data.json`. |
| `justfile` (changed) | New `policy-check` recipe (fmt, strict check, Regal, coverage ≥ 90%, tests); `check` now runs it. |
| `bootstrap/Brewfile` (changed) | `opa` and `regal`. |
| `infra/compose/compose.yaml` (changed) | The `opa` service (1.21.1-static by digest, token auth + `system.authz`, read-only policies, JSON decision logs, non-root, read-only root filesystem); rag-api gets `RAG_API_OPA_URL`, the `rag_api_opa_token` secret file and starts after OPA. |
| `scripts/new-dev-secrets.sh`, `.env.example` (changed) | Generate and document `OPA_API_TOKEN`. |
| `services/rag-api/src/rag_api/policy.py` | The fail-closed OPA client and the policy types (`Decision`, `SearchFilter`, `DocumentRef`, `PolicyEngine`, `PolicyUnavailable`). |
| `services/rag-api/src/rag_api/settings.py` (changed) | `opa_url` and `opa_token` (from `/run/secrets/rag_api_opa_token`). |
| `services/rag-api/src/rag_api/search.py` (changed) | Query filtered by the policy's groups and classifications; returns `Candidate`s with access facts for the post-check. |
| `services/rag-api/src/rag_api/main.py` (changed) | `get_policy`, `authorize(action)` (403 with reasons, 503 when OPA is down), search with pre-filter + post-check; no role names left. |
| `services/rag-api/pyproject.toml`, `uv.lock` (changed) | `httpx` becomes a runtime dependency of rag-api (the OPA client). |
| `services/rag-api/tests/conftest.py` | Shared test doubles: `FakeIdP`, `FakeSearch`, `FakePolicy` and fixtures. |
| `services/rag-api/tests/test_auth.py` (rewritten) | The 17 authentication tests on the shared fixtures. |
| `services/rag-api/tests/test_policy.py` | The 5 wiring tests: asks, obeys, fails closed, post-checks, never trusts the body. |
| `services/rag-api/tests/test_opa_live.py` | 4 tests of the real policy in a real OPA through the real client (skipped without `opa`). |
| `services/rag-api/tests/test_service.py` (changed) | Updated for the new search signature and settings; adds OPA-client tests (odd answers are errors, only a literal `true` allows, unreachable OPA). |
| `tests/test_policy_engine.py` | Repo-level checks: policy files, `data.json` vs the Keycloak realm, Regal config, Compose hardening and wiring, the token generator, recipes, Brewfile, ADR; runs `opa check`/`opa test` when `opa` is installed; opt-in live checks against OPA on 8181. |
| `tests/test_rag_api.py` (changed) | Expects rag-api's third secret and its dependency on `opa`. |
| `docs/adr/0018-use-opa-as-the-policy-decision-point.md`, `docs/adr/README.md` | ADR-0018 and its index row. |
| `docs/steps/step-18-policy-engine-opa.md` | This write-up. |

## Notes for this repository

- **Rego reconstructed from the PDF.** The policy, data and test files are the guide's content with the PDF's line
  wraps joined and tab indentation restored (what `opa fmt` produces). `opa fmt --list --fail`, `opa check
  --strict`, `regal lint` (Regal 0.43.0) and `opa test` (OPA 1.21.1) all pass: **21/21, coverage 98.2%**, exactly as
  the guide says.
- **The image digest is real.** `openpolicyagent/opa:1.21.1-static` resolved to
  `sha256:4675ab04…20838e` on Docker Hub (2026-10-12). Refresh it when you want updates.
- **The decision-log command uses `--no-log-prefix`.** `docker compose logs` prefixes each line with
  `opa-1  | `, which `jq` can't parse, so the doc above adds `--no-log-prefix` to the guide's command.
- **`httpx` is now a rag-api dependency.** The guide's `policy.py` imports `httpx`, which Step 17 only had as a dev
  dependency; without it the container would fail at import.
- **More tests than the guide counts.** The guide's three API test files give exactly its 26 (17 + 5 + 4). The
  repository also keeps `services/rag-api/tests/test_service.py` (now 16 tests, including OPA-client edge cases)
  and adds `tests/test_policy_engine.py` (13 static + 4 that need OPA or a running stack). The four Step 17 role
  tests in `test_auth.py` (missing role, admin role, service account can't search) are gone, as in the guide: the
  same questions are now answered by the policy tests (`test_user_may_not_use_admin`,
  `test_admin_role_comes_through`, `test_machine_may_ingest_but_not_search`) and the live-OPA tests.
- **What was validated here (Linux container, no Mac, no SOPS key).** `just policy-check` passed with the real
  `opa` and `regal` release binaries. OPA ran with the guide's flags and a throwaway token: Bob's decision returned
  `allow: true` with `["confidential","internal","public"]`; no token → 401; policy upload → 401 "request rejected
  by administrative policy"; `/health` → 200; an empty `OPA_API_TOKEN` still refuses every token (fail closed). The
  `opa` Compose service itself was started from this compose file (`up -d --no-deps opa`): it ran as uid 65532 with
  the read-only mount, the contractor-in-executives `readable_ids` query returned only `[1]`, and the decision log
  line parsed with `jq`. `uv sync`, ruff, strict mypy and the full pytest suite pass, including the four live-OPA
  tests. The rag-api image was not rebuilt here (the sandbox couldn't download the uv base image from ghcr.io); the
  Dockerfile is unchanged and `uv.lock` already includes `httpx`. The end-to-end demo (step 8) needs Keycloak, the
  gateway and the Mac-native models, so it wasn't run here.
