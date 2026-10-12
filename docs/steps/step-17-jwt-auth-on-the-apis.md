# Step 17 · JWT auth on the APIs

*Step 17 of 38 · Phase D · Identity & policy*

## At a glance

| | |
|---|---|
| **Goal** | Build the platform's first real service, `rag-api`, and make it check every Keycloak token properly before answering: signature, algorithm, issuer, audience, expiry, token type and calling app. A valid token becomes a **Principal** (who is calling, their groups and roles), which drives role checks and the document filter. |
| **Time** | About 2 hours. |
| **You'll end up with** | A shared, framework-free token verifier in `rag-common`, reused by every future service; `services/rag-api` (FastAPI) with a public health check, `/v1/me`, a role-protected admin endpoint, and permission-aware search whose groups come only from the verified token; 21 automated tests that attack the API with expired, forged, re-signed, wrong-audience, `alg: none` and algorithm-confusion tokens, all without Keycloak running; a small, non-root container image built with uv, running in Compose on `127.0.0.1:8000`; a live demo as a person, a machine, with no token and with a forged token; ADR-0017. |
| **New words** | Bearer token, Authorization header, token validation, `kid`, algorithm allow-list, `alg: none`, algorithm confusion, clock skew / leeway, key rotation, JWKS cache, 401 vs 403, `WWW-Authenticate`, Principal, dependency injection, fail closed, token introspection, opaque token, revocation, multi-stage build, non-root container, read-only filesystem. |

## The big idea

> **ANALOGY · THE DOOR GUARD**
> Step 16 opened the badge office. Today we train the door guard. A good guard doesn't just glance at a badge.
> They check, in order:
>
> - it's a real badge format, not a drawing
> - the hologram is genuine and untouched (signature)
> - it was issued by our badge office (issuer) and for this building (audience)
> - it hasn't expired, and it's a door badge, not a visitor sticker (type)
>
> Only then do they look at the department printed on it: does it open this room (role)? And for the filing
> cabinets inside, the department decides which folders you may open (groups → document filter).
>
> A guard who skips any one check lets someone in. Real breaches happen exactly this way.

```text
                              Authorization: Bearer eyJhbGciOi…
                                             │
   1 Format      2 Algorithm    3 Public key   4 Signature   5 Issuer       6 Audience    7 Time + type
   3 parts       RS256 only     from JWKS      nothing       our Keycloak   meant for     exp ± 30 s
   has a kid     no none/HS256  cached 5 min   changed?      realm rag?     rag-api?      Bearer · azp
                                             │
            Any check fails → 401 Unauthorized + WWW-Authenticate: Bearer error="invalid_token"
            Keycloak unreachable and key not cached → 503
                                             │ all pass
                                             ▼
        Principal                                         has the     no  → 403 Forbidden
        sub · username · client · groups · roles  ───────► role?
                                                                       yes → 200 · run the endpoint

        401 = we don't know who you are.   403 = we know who you are, and the answer is no.
```

*Figure 54. The seven checks every token passes before the API trusts it. Any failure gives 401; a valid token
becomes a Principal, and a missing role gives 403.*

## What we're doing

1. Write the token verifier in `rag-common`: framework-free, strictly typed.
2. Create `services/rag-api` with FastAPI: settings from environment and secret files, auth dependencies, four
   endpoints.
3. Write tests that attack the API, using our own test signing key instead of Keycloak.
4. Package it as a small, locked-down container and add it to Compose.
5. Call it for real as alice, carol and the ingestion worker; then with no token and a forged one.
6. Record ADR-0017.

## Why we're doing this

> **WHY THIS MATTERS**
> Until now, permission-aware search has used a hard-coded list of groups. In a real system, the groups must
> come from who is actually calling, and that is only safe if the API proves the token is genuine. A token check
> with one gap (forgetting the audience, accepting `alg: none`, trusting a group sent in the request body) means
> anyone can read everything. API authentication is the single most important control in front of your
> documents, and the most common place for subtle bugs.

| Need | How this step meets it |
|---|---|
| Only Keycloak-issued tokens accepted | Signature check against Keycloak's public keys (JWKS), RS256 only |
| Tokens for other apps rejected | Issuer and audience (`rag-api`) checks; allowed calling apps (`azp`) |
| Old or stolen tokens limited | Expiry required, 30 s clock leeway, 5-minute lifetime (Step 16) |
| ID tokens can't be misused | Token type must be `Bearer` |
| Keys change without downtime | Key cache with automatic re-fetch on unknown `kid` |
| What may you do? | Role checks per endpoint → 403 |
| What may you see? | Groups from the token only → document filter, fail closed |
| Cost and logs per person | Gateway calls tagged with `user = sub` |
| Proof it works | Negative tests for every attack, run on every commit |

> **IN A COMPANY**
> Security reviews and penetration tests always cover the API's token handling. Expect questions like:
>
> - Do you validate `aud`?
> - Do you pin the algorithm?
> - What happens when the identity provider rotates keys, or is down?
> - Can a user change their own groups?
>
> A test file that answers each question with a failing token is strong evidence. The OWASP API Security Top 10
> lists broken authentication and broken object-level authorisation at the top for a reason.

## Key ideas

| Term | Plain-English meaning |
|---|---|
| **Bearer token** | A token that works for whoever holds ("bears") it, sent as `Authorization: Bearer <token>`. Guard it like a password. |
| **Token validation** | Proving a token is genuine and meant for you before believing anything in it. |
| **`kid` (key id)** | A label in the token's header naming which of Keycloak's keys signed it. |
| **Algorithm allow-list** | Accepting only the expected signing algorithm (RS256), so attackers can't pick a weaker one. |
| **`alg: none`** | An unsigned token. Some old libraries accepted it as valid: a famous vulnerability. |
| **Algorithm confusion** | Re-signing a token with HS256 using the server's public key as the password. Blocked by the allow-list. |
| **Clock skew / leeway** | Machines' clocks differ slightly; a small tolerance (30 s) avoids rejecting fresh tokens. |
| **Key rotation** | Keycloak periodically switches to a new signing key; APIs must pick up new keys automatically. |
| **401 vs 403** | 401: "I don't know who you are" (no or bad token). 403: "I know who you are, and the answer is no." |
| **`WWW-Authenticate`** | The response header that tells a client a bearer token is required, or was invalid. |
| **Principal** | The verified caller: user id, username, calling app, groups, roles. |
| **Dependency injection** | FastAPI runs helper functions (like "get the caller") before an endpoint and passes in their results. |
| **Fail closed** | When unsure, deny. No groups means no documents, not all documents. |
| **Introspection / opaque token** | Asking the identity provider "is this token valid?" on every call; needed for tokens that aren't readable JWTs. |

> **IN PLAIN ENGLISH · THE OTHER NEW WORDS**
>
> - **JWKS cache**: our copy of Keycloak's public keys, kept for 5 minutes so we don't ask Keycloak on every request.
> - **Revocation**: cancelling a token early. With local checks it only bites when the 5-minute token expires.
> - **Multi-stage build**: a Dockerfile where one stage builds and a second, smaller stage only receives the result.
> - **Non-root container**: the process inside runs as an ordinary user (uid 10001), not as the all-powerful root.
> - **Read-only filesystem**: the container can't change its own files; only a small RAM scratch folder is writable.

### Where everything connects

```text
                                  0 · sign in (Step 16)                     ┌──────────────────────────┐
     ┌────────────────────┐ ─────────────────────────────────────────────►  │ Keycloak                 │
     │ rag-cli / rag-web  │                                                 │ keycloak:8080 (inside)   │
     │ your laptop        │                                                 └──────────────────────────┘
     └────────────────────┘                                                        ▲ 2 · public keys,
               │ 1 · Bearer token                                                  │     every 5 min
               ▼                                                                   │
     ┌─────────────────────────────────────┐   3 · embed     ┌──────────────────────────────────────┐
     │ rag-api :8000                       │ ──────────────► │ LiteLLM gateway                      │
     │ verifies every token locally        │                 │ user = sub (cost per person)         │
     │ non-root · read-only filesystem     │                 └──────────────────────────────────────┘
     └─────────────────────────────────────┘   4 · search    ┌──────────────────────────────────────┐
                                             ──────────────► │ rag-db (Postgres)                    │
                                                             │ acl_groups && token groups           │
                                                             └──────────────────────────────────────┘

  Token says iss = http://localhost:8180/realms/rag (the public name). rag-api fetches keys from
  http://keycloak:8080 (the internal name). Same Keycloak, two addresses: check the issuer, not the URL you called.
```

*Figure 55. The request path. You sign in at Keycloak; rag-api checks your token with cached public keys, embeds
the question through the gateway (tagged with your user id), and searches Postgres with the groups from your token.*

### Two ways to check a token

```text
  LOCAL VALIDATION · OUR CHOICE                        INTROSPECTION (RFC 7662)
  + No call to Keycloak per request                    + Revocation takes effect instantly
  + Fast (well under 1 ms) once keys are cached        + Works with opaque (non-JWT) tokens
  + Keeps working if Keycloak is briefly down          - An extra network call on every request
  - A revoked token still works until it expires       - Keycloak load grows with API traffic
    …so keep access tokens short (5 min)               - Keycloak down = API down

  Common pattern: validate locally everywhere; introspect (or re-check the session) only for high-risk actions.
```

*Figure 56. Local validation checks the signature with cached keys: fast and resilient, but a revoked token works
until it expires. Introspection asks Keycloak every time: instant revocation, at the cost of a network call per
request.*

> **WHY LOCAL VALIDATION, AND WHAT ABOUT REVOCATION?**
> We validate locally:
>
> - The API caches Keycloak's public keys and checks signatures itself.
> - That's fast and doesn't hammer Keycloak.
> - It also keeps working through a Keycloak restart.
>
> The trade-off is that revoking a token (say, an employee leaves) only takes full effect when it expires. That's
> why Step 16 set access tokens to 5 minutes, and refresh tokens die at logout. For very sensitive actions
> (deleting a collection, exporting data), you can additionally introspect or require a fresh sign-in. That's a
> decision per action, not per API.

## How to do it

On your Mac, in the project folder, on a feature branch:

```bash
cd ~/dev/rag-platform
git switch -c feat/rag-api-auth
```

### 1 · The token verifier (shared library)

```bash
uv add --package rag-common "pyjwt[crypto]"
```

It lives in `rag-common` because every service that accepts tokens (this API, workers, the evaluation runner)
must check them identically. One implementation, one set of tests.

**File · `libs/rag-common/src/rag_common/auth.py`** (committed in full; the heart of it):

```python
# Only the algorithm Keycloak actually uses. Never "none", never HS256: accepting HS256 would let an
# attacker sign a token with our PUBLIC key as the shared secret (the "algorithm confusion" attack).
ALLOWED_ALGORITHMS = ["RS256"]
SERVICE_ACCOUNT_PREFIX = "service-account-"  # Keycloak's username for client-credentials identities


class AuthError(Exception):
    """The token is missing or not acceptable. Maps to HTTP 401."""


class KeyServiceUnavailable(Exception):  # noqa: N818 - reads better than ...Error here
    """The identity provider's keys could not be fetched. Maps to HTTP 503, not 401."""


@dataclass(frozen=True)
class OIDCSettings:
    issuer: str  # must equal the token's "iss" exactly
    audience: str  # this API's name; must appear in the token's "aud"
    jwks_url: str  # where the public keys are published
    allowed_clients: frozenset[str] = frozenset()  # apps allowed to call us ("azp"); empty = any
    leeway_seconds: int = 30  # tolerance for small clock differences


@dataclass(frozen=True)
class Principal:
    """Who is calling: the facts every authorisation decision is based on."""

    subject: str  # stable user id ("sub"); use this in logs and the database, not the username
    username: str
    client_id: str  # the app the token was issued to ("azp")
    groups: frozenset[str]
    roles: frozenset[str]
    # + is_service_account (username starts with "service-account-") and has_role(role)


class TokenVerifier:
    def __init__(self, settings: OIDCSettings, keys: SigningKeySource | None = None) -> None:
        self._s = settings
        # Caches keys for 5 minutes and re-fetches automatically when it sees an unknown key id,
        # which is what happens right after Keycloak rotates its signing key.
        self._keys = keys or jwt.PyJWKClient(
            settings.jwks_url, cache_keys=True, lifespan=300, timeout=5
        )

    def verify(self, token: str) -> Principal:
        try:
            key = self._keys.get_signing_key_from_jwt(token)
            claims: dict[str, Any] = jwt.decode(
                token, key=key, algorithms=ALLOWED_ALGORITHMS,
                audience=self._s.audience, issuer=self._s.issuer, leeway=self._s.leeway_seconds,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWKClientConnectionError as e:
            raise KeyServiceUnavailable(str(e)) from e
        except jwt.PyJWTError as e:
            # bad signature, expired, wrong audience or issuer, unknown key, malformed token…
            raise AuthError(type(e).__name__) from e

        # Keycloak marks access tokens "Bearer"; ID tokens ("ID") must never be used to call APIs.
        if claims.get("typ") != "Bearer":
            raise AuthError("not an access token")
        client_id = str(claims.get("azp", ""))
        if self._s.allowed_clients and client_id not in self._s.allowed_clients:
            raise AuthError(f"client {client_id!r} may not call this API")

        realm_access = claims.get("realm_access") or {}
        return Principal(
            subject=str(claims["sub"]),
            username=str(claims.get("preferred_username", "")),
            client_id=client_id,
            groups=_str_set(claims.get("groups"), "groups"),
            roles=_str_set(realm_access.get("roles"), "realm_access.roles"),
        )
```

`SigningKeySource` is a small `Protocol` ("anything with `get_signing_key_from_jwt`"): `PyJWKClient` in
production, a fake in tests. `_str_set` turns a claim into a `frozenset[str]` and raises `AuthError("malformed
claim …")` if it isn't a list of strings.

> **READING THE VERIFIER**
>
> - `ALLOWED_ALGORITHMS = ["RS256"]`: the algorithm is ours to choose, never the token's. This one line blocks
>   both `alg: none` and algorithm confusion.
> - `PyJWKClient`: downloads Keycloak's public keys, keeps them for 5 minutes and, when it meets a `kid` it
>   doesn't know, fetches again. After Keycloak rotates its key, the API catches up automatically.
> - `jwt.decode(...)`: checks the signature, issuer, audience and expiry together. `require` makes those claims
>   mandatory: a token without `exp` is rejected instead of living forever.
> - Two kinds of failure:
>   - a bad token raises `AuthError` (401: the caller's problem)
>   - unreachable keys raise `KeyServiceUnavailable` (503: our problem)
>
>   Mixing these up would make clients throw away good tokens during an outage.
> - `typ == "Bearer"`: Keycloak marks access tokens `Bearer` and ID tokens `ID`. An ID token was never meant for
>   APIs.
> - `allowed_clients`: only our own apps (`azp`) may call. A token issued to some other app in the realm is
>   refused, even if it happens to carry our audience.
> - `_str_set`: claims are untrusted input until checked. A `groups` claim that isn't a list of strings is
>   rejected, never guessed at.
> - `Principal`: an immutable, typed result. Everything downstream uses this, never the raw token.

> **WATCH OUT · THE 30-SECOND COOL-DOWN ON UNKNOWN KEYS**
> Current PyJWT (2.15) re-fetches the JWKS for an unknown `kid` at most once every 30 seconds (its
> `cooldown_duration`). That stops a flood of tokens with made-up `kid`s from turning your API into a weapon
> against Keycloak. The side effect: if a rotated key appears within 30 s of the last download, tokens signed
> with it get 401 until the cool-down passes. Keycloak publishes a new key as soon as you add it, so in practice
> add the new key a minute before making it the active one (or just retry). `libs/rag-common/tests/
> test_auth_verifier.py` shows both halves.

### 2 · The API service

```bash
mkdir -p services/rag-api/src/rag_api services/rag-api/tests
touch services/rag-api/src/rag_api/__init__.py services/rag-api/src/rag_api/py.typed
```

**File · `services/rag-api/pyproject.toml`**

```toml
[project]
name = "rag-api"
version = "0.1.0"
description = "The RAG platform's public API"
requires-python = ">=3.12,<3.13"
dependencies = [
    "rag-common",
    "fastapi>=0.140",
    "uvicorn>=0.50",
    "pydantic-settings>=2.10",
    "psycopg[binary]>=3.2",
    "pgvector>=0.4",
    "openai>=2.0",
]

[tool.uv.sources]
rag-common = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

This is the first service, so the workspace now includes `services/*` (as Step 4 promised), and mypy and pytest
learn about it. **File · `pyproject.toml` (root: changes)**:

```toml
[dependency-groups]
dev = [..., "httpx"]                          # httpx: FastAPI's test client (already there since Step 16)

[tool.uv.workspace]
members = ["libs/*", "services/*"]

[tool.ruff.lint.isort]
known-first-party = ["rag_common", "rag_api"]

[tool.mypy]
files = ["libs/rag-common/src", "services/rag-api/src", "services/rag-api/tests", "scripts", "tests"]

[tool.pytest.ini_options]
testpaths = ["libs", "services", "tests"]
```

```bash
uv add --dev httpx
uv sync --all-packages
```

**Settings.** Plain values come from `RAG_API_*` environment variables. Secrets come from files in
`/run/secrets`, where Compose mounts them. pydantic-settings reads both natively, so this service needs no
wrapper script (unlike the off-the-shelf images in earlier steps).

**File · `services/rag-api/src/rag_api/settings.py`**

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAG_API_", secrets_dir="/run/secrets")

    oidc_issuer: str  # http://localhost:8180/realms/rag
    oidc_audience: str = "rag-api"
    oidc_jwks_url: str  # http://keycloak:8080/realms/rag/protocol/openid-connect/certs
    allowed_clients: list[str] = ["rag-web", "rag-cli", "ingestion-worker"]

    gateway_url: str = "http://litellm:4000/v1"
    gateway_key: SecretStr  # file /run/secrets/rag_api_gateway_key
    db_host: str = "rag-db"
    db_password: SecretStr  # file /run/secrets/rag_api_db_password
```

> **IN PLAIN ENGLISH · HOW THE SECRET FILES ARE FOUND**
> pydantic-settings looks for a file named *prefix + field name* in `secrets_dir`: `RAG_API_` + `gateway_key` →
> `/run/secrets/rag_api_gateway_key` (names are matched case-insensitively). That is exactly the name Compose gives
> the secret, so nothing else is needed.

**Search.** This is Step 11's permission-aware query, moved into the service. Two details matter:

- An empty group set returns nothing (fail closed).
- The gateway call passes `user=<sub>`, so LiteLLM records cost and logs per person, not just per app.

**File · `services/rag-api/src/rag_api/search.py`**

```python
SQL = """
SELECT d.title, d.classification, round((1 - (c.embedding <=> %(q)s))::numeric, 3)::float AS score
FROM rag.chunks c JOIN rag.documents d ON d.id = c.document_id
WHERE d.deleted_at IS NULL AND d.acl_groups && %(groups)s
ORDER BY c.embedding <=> %(q)s
LIMIT %(k)s
"""


class SearchBackend(Protocol):
    def search(self, query: str, *, groups: frozenset[str], k: int, user: str) -> list[Hit]: ...


class PgSearch:
    def __init__(self, s: Settings) -> None:
        self._gw = OpenAI(base_url=s.gateway_url, api_key=s.gateway_key.get_secret_value())
        self._dsn = (
            f"host={s.db_host} dbname=rag user=rag_app password={s.db_password.get_secret_value()}"
        )

    def search(self, query: str, *, groups: frozenset[str], k: int, user: str) -> list[Hit]:
        if not groups:
            return []  # fail closed: no groups, no documents
        # "user" lets the gateway attribute cost and logs to the real person (Step 10 spend tracking)
        emb = self._gw.embeddings.create(model="embedder", input=[INSTRUCTION + query], user=user)
        with psycopg.connect(self._dsn) as conn:
            register_vector(conn)
            rows = conn.execute(
                SQL, {"q": HalfVector(emb.data[0].embedding), "groups": sorted(groups), "k": k}
            ).fetchall()
        return [Hit(title=t, classification=c, score=sc) for t, c, sc in rows]
```

`INSTRUCTION` is the same query instruction as Step 11 ("Instruct: Given an employee question, retrieve passages
from company documents that answer it\nQuery:"), and `Hit` is a small pydantic model (title, classification,
score).

**The app.** Three dependencies do the security work. FastAPI runs them before each endpoint:

- `current_principal`: no token or a bad token gives 401, otherwise a Principal.
- `require_role("…")`: the right role, or 403.
- `get_search`: the search backend (swapped for a fake in tests).

**File · `services/rag-api/src/rag_api/main.py`** (the security part; the file also has the cached
`get_settings()`, `get_verifier()` and `get_search()` factories):

```python
bearer = HTTPBearer(auto_error=False)  # we build the 401 ourselves, with the standard header


def unauthorized(error: str = "invalid_token") -> HTTPException:
    # RFC 6750: tell the client it needs a (new) bearer token, but don't say what exactly was wrong
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Not authenticated",
        headers={"WWW-Authenticate": f'Bearer realm="rag-api", error="{error}"'},
    )


def current_principal(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    verifier: Annotated[TokenVerifier, Depends(get_verifier)],
) -> Principal:
    if creds is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Not authenticated",
            headers={"WWW-Authenticate": 'Bearer realm="rag-api"'},
        )
    try:
        return verifier.verify(creds.credentials)
    except KeyServiceUnavailable as e:
        log.error("cannot fetch signing keys: %s", e)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Identity provider unavailable"
        ) from e
    except AuthError as e:
        log.warning("rejected token: %s", e)  # the reason, never the token itself
        raise unauthorized() from e


def require_role(role: str) -> Callable[[Principal], Principal]:
    def check(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
        if not principal.has_role(role):
            log.warning("forbidden: sub=%s lacks role %s", principal.subject, role)
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role {role}")
        return principal

    return check
```

The four endpoints:

| Endpoint | Who may call | What it returns |
|---|---|---|
| `GET /healthz` | anyone, no token (public on purpose: Docker and Kubernetes probes have no token) | `{"status": "ok"}` |
| `GET /v1/me` | any valid token | the Principal: subject, username, client_id, groups, roles, service_account |
| `POST /v1/search` | role `rag-user` | `list[Hit]`; body `{"query": 1–2000 chars, "k": 1–20, default 5}` |
| `GET /v1/admin/ping` | role `rag-admin` | `{"status": "ok", "admin": <username>}` |

```python
@app.post("/v1/search")
def search(
    req: SearchRequest,
    p: Annotated[Principal, Depends(require_role("rag-user"))],
    backend: Annotated[SearchBackend, Depends(get_search)],
) -> list[Hit]:
    # The groups come ONLY from the verified token, never from the request body.
    return backend.search(req.query, groups=p.groups, k=req.k, user=p.subject)
```

> **THE ONE RULE THAT MATTERS MOST**
> `/v1/search` takes the groups from `p.groups`, the verified token, and the request body has no `groups` field at
> all. If an API ever accepted "my groups are…" from the caller, every user could read every document. The test
> suite below sends a sneaky `"groups": ["executives"]` field to prove it's ignored.

> **NEVER LOG TOKENS**
> `current_principal` logs why a token was rejected (`InvalidSignatureError`, `ExpiredSignatureError` …) but never
> the token itself. A token in a log file is a working credential for anyone who can read the logs. Step 21's log
> pipeline can also scrub `Authorization` headers as a second line of defence.

### 3 · Tests that attack the API

No Keycloak needed: the test file plays the identity provider. It creates its own RSA key pair, signs tokens with
it, and swaps in a fake key source through FastAPI's `dependency_overrides`. Every bad token is a one-line entry in
a table, so adding a new attack later is trivial.

**File · `services/rag-api/tests/test_auth.py`** (committed in full). The building blocks:

- `KEY` (ours) and `OTHER_KEY` (an attacker's): fresh 2048-bit RSA keys per test run.
- `FakeKeys`: stands in for Keycloak's JWKS endpoint and knows exactly one public key, with `kid` `test-key-1`.
- `FakeSearch`: records which groups and user each search was called with.
- `claims(**overrides)`: a realistic Keycloak access-token payload for alice (`iss`, `aud: ["rag-api",
  "account"]`, `azp: rag-cli`, `typ: Bearer`, `sub`, `preferred_username`, `iat`, `exp`, `groups`,
  `realm_access.roles`); passing `None` removes a claim.
- `mint(...)`: signs those claims with any key, algorithm and `kid`.

The attack table:

```python
BAD_TOKENS = {
    "expired": lambda: mint(exp=int(time.time()) - 120, iat=int(time.time()) - 500),
    "wrong audience": lambda: mint(aud="account"),
    "wrong issuer": lambda: mint(iss="http://evil.example/realms/rag"),
    "missing expiry": lambda: mint(exp=None),
    "tampered payload": lambda: _tamper(mint()),          # adds "executives" to groups, keeps the signature
    "signed by another key": lambda: mint(key=OTHER_KEY),
    "unknown key id": lambda: mint(kid="not-ours"),
    "alg none": _alg_none,                                # unsigned token
    "alg confusion HS256": _hs256_with_public_key,        # HMAC with our PUBLIC key as the secret, built by hand
    "ID token, not access token": lambda: mint(typ="ID"),
    "client not allowed": lambda: mint(azp="some-other-app"),
    "malformed groups claim": lambda: mint(groups="executives"),
    "garbage": lambda: "not-a-jwt",
}


@pytest.mark.parametrize("make", BAD_TOKENS.values(), ids=BAD_TOKENS.keys())
def test_bad_tokens_get_401(client: TestClient, make: Any) -> None:
    r = call(client, make())
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"].startswith("Bearer")
```

…plus the happy path (health without a token, `/v1/me` with a valid token, search that uses the token's groups and
ignores a `groups` field in the body), no token at all (401 with exactly `Bearer realm="rag-api"`), and the
permission tests (missing role → 403, `rag-admin` allowed on the admin endpoint, the machine can't search, a token
that expired 10 s ago is still accepted within the 30 s leeway).

```bash
just check                         # ruff, mypy (strict) and pytest
```

> **WHAT YOU SHOULD SEE**
> `21 passed` in `services/rag-api/tests/test_auth.py`:
>
> - 3 happy-path tests: health, `/v1/me`, and search using the token's groups.
> - 13 attacks that each get 401 with a `WWW-Authenticate` header: expired, wrong audience, wrong issuer, missing
>   expiry, tampered payload, signed by another key, unknown key id, `alg: none`, algorithm confusion, ID token,
>   unlisted app, malformed groups, garbage.
> - No token at all: 401 with the challenge header.
> - 4 permission tests: missing role gives 403; the admin role is allowed; the machine can't search; small clock
>   skew is tolerated.
>
> mypy reports no issues in strict mode. These tests now run on every push (Step 5's hooks) and later in CI
> (Step 27).

> **WHY TESTS WITHOUT KEYCLOAK?**
> Tests that need a running identity server are slow, flaky and skipped when people are in a hurry. Tests with a
> local key run in about a second, offline, every time. A smaller set of integration tests against the real stack
> comes with the evaluation harness and CI (Steps 26–27). Most security checks belong in fast unit tests.

This repository adds a few more fast tests around the guide's 21 (see "Notes for this repository"):
`services/rag-api/tests/test_service.py` (Keycloak down → 503 without a challenge header, the OpenAPI schema has no
`groups` field, settings read from secret files, the Postgres backend fails closed and tags the gateway call with
the user) and `libs/rag-common/tests/test_auth_verifier.py` (the real `PyJWKClient` against a local JWKS server:
caching, key rotation, unreachable key service).

### 4 · A small, locked-down container

**File · `services/rag-api/Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1
# Build context: the repository root (so the workspace lockfile and libs/ are available).

# ---- stage 1: build the virtual environment with uv ----
FROM ghcr.io/astral-sh/uv:0.11.32@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c AS uv
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# 1) dependencies only (cached until uv.lock changes)
COPY pyproject.toml uv.lock ./
COPY libs/rag-common/pyproject.toml libs/rag-common/
COPY services/rag-api/pyproject.toml services/rag-api/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package rag-api --no-install-workspace
# 2) then our own code
COPY libs/rag-common libs/rag-common
COPY services/rag-api services/rag-api
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package rag-api --no-editable

# ---- stage 2: the small runtime image (no uv, no compilers, no source tree) ----
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
RUN useradd --system --uid 10001 --no-create-home app
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
CMD ["uvicorn", "rag_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
```

> **READING THE DOCKERFILE**
>
> - Two stages: the first has uv and builds the environment; the second copies only the finished `.venv`. No uv,
>   no compilers, no source tree, no dev tools in the image you run.
> - Dependencies first, code second: the slow dependency layer is cached until `uv.lock` changes, so rebuilding
>   after a code change takes seconds.
> - `--locked`: the build fails if `uv.lock` doesn't match `pyproject.toml`. Exactly what's tested is what ships.
> - `--no-editable`: our packages are installed into the environment, so the source folders aren't needed at
>   runtime.
> - `USER 10001`: the process runs as an ordinary user, not root.
> - Base image: pin `python:3.12-slim-bookworm` (and the uv image) by digest like every other image, using
>   `docker buildx imagetools inspect`. Step 27 adds image scanning and an SBOM.

A root **`.dockerignore`** keeps the build context to what the Dockerfile copies (`pyproject.toml`, `uv.lock`,
`libs/`, `services/`), so `.git`, `secrets/`, the PDFs and your `.venv` never reach the Docker daemon.

**File · `infra/compose/compose.yaml` (add)**

```yaml
services:
  rag-api:
    build:
      context: ../..                                          # repository root
      dockerfile: services/rag-api/Dockerfile
    image: rag-platform/rag-api:dev
    environment:
      RAG_API_OIDC_ISSUER: http://localhost:8180/realms/rag   # must match the token's "iss"
      RAG_API_OIDC_JWKS_URL: http://keycloak:8080/realms/rag/protocol/openid-connect/certs
      RAG_API_GATEWAY_URL: http://litellm:4000/v1
      RAG_API_DB_HOST: rag-db
    secrets:
      - rag_api_gateway_key                                   # -> /run/secrets/rag_api_gateway_key
      - rag_api_db_password                                   # -> /run/secrets/rag_api_db_password
    ports:
      - "127.0.0.1:8000:8000"
    # (the guide's read_only: true: see the WATCH OUT box below)
    tmpfs: [/tmp]                                             # scratch space in RAM only
    cap_drop: [ALL]                                           # no special Linux privileges at all
    security_opt: ["no-new-privileges:true"]
    depends_on:
      keycloak: { condition: service_healthy }
      rag-db:   { condition: service_healthy }
      litellm:  { condition: service_healthy }
    restart: unless-stopped
    deploy:
      resources:
        limits: { memory: 512m, cpus: "1" }

secrets:
  rag_api_gateway_key: { environment: RAG_API_GATEWAY_KEY }   # the Step 10 virtual key
  rag_api_db_password: { environment: RAG_DB_APP_PASSWORD }   # the Step 11 rag_app role
```

> **WATCH OUT · `read_only: true` AND SECRETS FROM ENVIRONMENT VARIABLES**
> The guide also sets `read_only: true` (the container can't modify its own files). Current Docker Compose refuses
> to start that combination: secrets that come from environment variables (which is how `sops exec-env` hands
> them over, Step 6) are *copied into* the container, and Compose stops with
> `cannot create secret "…" in read-only service rag-api: "file" is the sole supported option`. The only
> Compose-native alternative, `file:` secrets, would mean writing the decrypted values to disk, which Step 6 rules
> out. So this repository leaves `read_only` out and keeps the protection it was there for: the app runs as uid
> 10001 and everything under `/app` belongs to root, so the process can't change its own code
> (`touch /app/.venv/...` → `Permission denied`), and it has no capabilities and no way to gain any. On Kubernetes
> (later steps), `readOnlyRootFilesystem: true` works together with secret volumes, and it comes back there.

> **ISSUER VS ADDRESS, ONE MORE TIME**
> The token's issuer is `http://localhost:8180/realms/rag`, Keycloak's public name (Step 16's `KC_HOSTNAME`).
> Inside Compose, rag-api reaches Keycloak by its internal name, `keycloak:8080`. That's why issuer and JWKS address
> are two settings: the verifier compares the issuer text, and fetches keys from wherever Keycloak is reachable.
> Setting the issuer to `http://keycloak:8080/…` would reject every real token.

**File · `justfile` (add)**

```make
# Rebuild and restart the API after code changes (Step 17)
api-up:
    sops exec-env secrets/dev.enc.env 'docker compose -f infra/compose/compose.yaml up -d --build rag-api'

# Call the API as a person, a machine, with no token and with a forged token
api-demo:
    just with-secrets uv run --with httpx scripts/api_demo.py
```

```bash
just api-up && just ps                                    # rag-api becomes healthy in a few seconds
curl -s http://127.0.0.1:8000/healthz                     # {"status":"ok"}
curl -si http://127.0.0.1:8000/v1/me | head -5            # 401 + WWW-Authenticate: Bearer realm="rag-api"
docker compose -f infra/compose/compose.yaml exec rag-api id   # uid=10001(app): not root
```

`RAG_API_GATEWAY_KEY` is the `rag-api-dev` virtual key you created with `just gateway-admin` in Step 10 and stored
with `just secrets-edit`; `RAG_DB_APP_PASSWORD` has been in the secrets file since Step 11.

### 5 · Call it for real

**File · `scripts/api_demo.py`** signs in as a person with the device flow (you approve in the browser; the script
never sees your password), as the ingestion worker with client credentials, and calls the API six ways:

```python
def main() -> None:
    question = {"query": "What is the plan for hybrid work?", "k": 3}
    person = person_token()
    call("person", "GET", "/v1/me", person)
    call("person", "POST", "/v1/search", person, json=question)
    call("person (not an admin)", "GET", "/v1/admin/ping", person)

    machine = machine_token()
    call("machine", "GET", "/v1/me", machine)
    call("machine (no rag-user role)", "POST", "/v1/search", machine, json=question)

    call("no token", "GET", "/v1/me", None)
    call("forged token (last chars changed)", "GET", "/v1/me", forge(person))
```

```bash
just api-demo                      # sign in as alice in a private window; run again as carol
```

> **WHAT YOU SHOULD SEE (AS ALICE)**
>
> | Caller | Call | Result |
> |---|---|---|
> | person | `GET /v1/me` | 200: `alice`, groups `all-staff`, `engineering`, role `rag-user` |
> | person | `POST /v1/search` | 200: Remote work policy, Parking. No executive document. |
> | person (not an admin) | `GET /v1/admin/ping` | 403 |
> | machine | `GET /v1/me` | 200: `service-account-ingestion-worker`, role `rag-ingest`, no groups |
> | machine (no rag-user role) | `POST /v1/search` | 403 |
> | no token | `GET /v1/me` | 401 |
> | forged token | `GET /v1/me` | 401 |
>
> Run it again as carol. Her search now returns Exec offsite, because her token says `executives`. That's the
> moment Step 11's hard-coded `["all-staff"]` becomes a real, signed identity.
>
> Run `just api-demo` as dave. `/v1/admin/ping` returns 200, because his `rag-admin` role came from the
> `platform-admins` group.
>
> Finally, look at LiteLLM's spend logs (`http://127.0.0.1:4000/ui` → Logs). Each embedding call now shows the user
> id of the person who asked.

> **CHANGE A GROUP, WAIT FOR THE NEXT TOKEN**
> Remove carol from `executives` in the Keycloak console and search again straight away: she still sees the offsite
> document until her current token expires (at most 5 minutes). That's the local-validation trade-off from the
> diagram above, now visible. Sign in again and the document disappears.

With the stack up, the live part of `tests/test_rag_api.py` checks the same things automatically:
`just with-secrets uv run pytest tests/test_rag_api.py`.

### 6 · Record the decision

```bash
just adr "Validate JWTs locally in every service"
```

**File · `docs/adr/0017-validate-jwts-locally-in-every-service.md`**: every service validates tokens itself with
`rag_common.auth.TokenVerifier` (PyJWT): RS256 only; keys from Keycloak's JWKS (cached 5 min, re-fetched on unknown
`kid`); issuer, audience `rag-api`, `exp`/`iat`/`sub` required, 30 s leeway; `typ` must be `Bearer`; `azp` must be
an allowed client. Invalid token → 401 with `WWW-Authenticate`; key service unreachable → 503; missing role → 403.
Groups only from the verified token; empty groups match no documents; gateway calls carry `user=sub`; tokens are
never logged. Alternatives considered: introspection per request, validation only at an API gateway,
python-jose / Authlib, Keycloak-specific client libraries. Consequences: fast, resilient, one shared verifier; but
revocation is delayed by up to 5 minutes, and stolen bearer tokens can be replayed (DPoP / mTLS are the upgrade).

```bash
git add -A
git commit -m "feat(rag-api): first service with JWT validation, RBAC and permission-aware search"
git push -u origin feat/rag-api-auth
gh pr create --fill && gh pr merge --squash --delete-branch
git switch main && git pull
```

## Benefits

- Real identity end to end: a person's sign-in now decides which documents they can retrieve.
- Every known token attack blocked, and proven by tests that run on each push.
- Reusable: one verifier in `rag-common` for every service, framework-free and strictly typed.
- Resilient: cached keys, automatic rotation and 503 (not 401) when Keycloak is unreachable.
- Clear outcomes: 401 vs 403 vs 503, with the standard challenge header.
- Accountability: gateway cost and logs per person, not just per app.
- A hardened first container: non-root, no capabilities, minimal contents.

## Drawbacks and risks

- Revocation delay: a disabled user keeps access for up to 5 minutes.
- Bearer tokens can be replayed if stolen (from a log, a browser extension, a proxy). Mitigations: HTTPS
  everywhere, short lifetimes, never logging tokens; later DPoP or mTLS.
- Group changes apply at the next token, which can surprise people (see the warning above).
- Configuration traps: wrong issuer text or JWKS address breaks every request. The tests can't catch a wrong
  production config; a smoke test after deploy can.
- Coarse authorisation only: "has role X" and "shares a group" don't express rules like "confidential documents
  only for full-time staff". That's Step 18.

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| Local JWT validation in the service (our choice) | Each service checks signatures with cached public keys | Default for internal APIs with short-lived tokens |
| Token introspection | Ask Keycloak about every token | Opaque tokens, or instant revocation is a hard requirement |
| Edge validation (Kong, Envoy `jwt_authn`, APISIX, oauth2-proxy) | A gateway in front checks tokens | Many services or languages; still validate in services that make decisions |
| Service mesh (Istio `RequestAuthentication`) | The sidecar proxy checks tokens | Kubernetes with a mesh already in place |
| Sender-constrained tokens (DPoP, mTLS-bound) | Token only works with the client's private key | High-risk APIs, regulated sectors |
| Other libraries (Authlib/joserfc, `fastapi-azure-auth`, Keycloak adapters) | Different code for the same checks | Team preference or a specific provider |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Internal API, short-lived JWTs | Local validation with JWKS caching (this step) |
| Employee off-boarding must be instant | Shorter tokens + introspection for sensitive endpoints, or session checks |
| Many services in different languages | Gateway or mesh validation + a thin check in each service |
| Public API for partners | Separate audience and client per partner; rate limits; consider DPoP or mTLS |
| Machine-to-machine | Client credentials, its own role (`rag-ingest`), no human groups |
| Browser single-page app | Auth code + PKCE; tokens kept in memory, or a backend-for-frontend |

## Common mistakes

- Decoding without verifying (`verify_signature=False`) "just for now".
- Letting the token choose the algorithm, or allowing HS256 next to RS256.
- Skipping the audience check, so any token from the realm works on your API.
- Setting the issuer to the internal URL (`keycloak:8080`) and rejecting every real token.
- Fetching JWKS on every request (slow, and a self-inflicted outage) or caching it forever (breaks on key
  rotation).
- Accepting ID tokens as access tokens.
- Reading groups or roles from the request instead of the token.
- Returning 403 for a bad token (it's 401), or 401 when Keycloak is down (it's 503).
- Logging the `Authorization` header or whole request objects.
- Running the container as root with a writable filesystem.

## Done when

- [ ] `rag_common.auth` verifies RS256 tokens with issuer, audience, expiry, type and calling-app checks
- [ ] `services/rag-api` is a workspace member; `just check` shows ruff clean, mypy strict clean, 21 passed in
      `test_auth.py`
- [ ] rag-api runs in Compose on `127.0.0.1:8000` as uid 10001, unable to modify its own code (read-only
      filesystem where the platform allows it, see the WATCH OUT box)
- [ ] `/healthz` works without a token; `/v1/me` without a token gives 401 with `WWW-Authenticate`
- [ ] `just api-demo`: alice sees no executive document, carol does; the admin endpoint gives 403 to alice and 200
      to dave; the machine can't search; the forged token gets 401
- [ ] LiteLLM logs show the user id for each embedding call
- [ ] ADR-0017 is merged through a PR

## Recap

> **RECAP**
> The platform has its first service and its door guard:
>
> - Every request to rag-api must carry a Keycloak token that passes seven checks. Any failure gets a precise 401,
>   403 or 503.
> - A valid token becomes a typed Principal. Its roles gate endpoints, and its groups, taken only from the token,
>   filter the documents.
> - 21 attack tests prove it on every push, and the service ships as a small, non-root, locked-down container.
>
> The rules are still simple, though: "has a role" and "shares a group". Step 18 moves authorisation into a policy
> engine, so rules like classification levels, ownership and relationships live in reviewed policy code instead of
> `if` statements.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `libs/rag-common/src/rag_common/auth.py` | The shared, framework-free token verifier: RS256 allow-list, cached JWKS with re-fetch on unknown `kid`, issuer / audience / expiry / type / `azp` checks, `AuthError` (401) vs `KeyServiceUnavailable` (503), and the frozen `Principal`. |
| `libs/rag-common/pyproject.toml`, `uv.lock` (changed) | `pyjwt[crypto]` becomes a `rag-common` dependency. |
| `libs/rag-common/tests/test_auth_verifier.py` | The verifier against a real local JWKS server: Principal fields, one download for many requests, key rotation after the 30 s cool-down, unknown `kid` → 401, unreachable keys → 503, service accounts, malformed claims. |
| `libs/rag-common/README.md` (changed) | How to use `rag_common.auth`. |
| `services/rag-api/pyproject.toml` | The first service package (FastAPI, uvicorn, pydantic-settings, psycopg, pgvector, openai; `rag-common` from the workspace; hatchling build). |
| `services/rag-api/src/rag_api/__init__.py`, `py.typed` | The package and its "I ship type hints" marker. |
| `services/rag-api/src/rag_api/settings.py` | `RAG_API_*` settings from the environment, the gateway key and database password from `/run/secrets` files. |
| `services/rag-api/src/rag_api/search.py` | Step 11's permission-aware pgvector search as a backend: fails closed on no groups, tags the gateway call with `user=sub`, connects as `rag_app`. |
| `services/rag-api/src/rag_api/main.py` | The FastAPI app: `current_principal` (401 / 503), `require_role` (403), `/healthz`, `/v1/me`, `/v1/search`, `/v1/admin/ping`. |
| `services/rag-api/tests/test_auth.py` | The guide's 21 tests: happy path, 13 bad tokens, no token, and four permission tests, all with a self-made RSA key instead of Keycloak. |
| `services/rag-api/tests/test_service.py` | Extra service tests: Keycloak down → 503, OpenAPI has the four endpoints and no `groups` field, settings from secret files, the Postgres backend's fail-closed and per-user behaviour. |
| `services/rag-api/Dockerfile` | Two-stage, digest-pinned uv build; runtime image with only the `.venv`, uid 10001, healthcheck, no server header. |
| `.dockerignore` | Sends only the workspace files, `libs/` and `services/` to the Docker daemon. |
| `pyproject.toml`, `uv.lock` (changed) | Workspace members `libs/*` and `services/*`; `rag_api` first-party for isort; mypy checks the service source and tests; pytest collects `services`. |
| `services/.gitkeep` (removed) | The folder now has real content. |
| `infra/compose/compose.yaml` (changed) | The `rag-api` service (127.0.0.1:8000, no capabilities, no-new-privileges, RAM `/tmp`, limits, healthy dependencies) and its two secrets. |
| `justfile` (changed) | `just api-up` and `just api-demo`. |
| `scripts/api_demo.py` | Calls the API as a person (device flow), a machine (client credentials), with no token and with a forged token. |
| `tests/test_rag_api.py` | Static checks of the workspace, Dockerfile, Compose service, recipes, demo and ADR; live checks (opt-in) against a running rag-api and Keycloak. |
| `docs/adr/0017-validate-jwts-locally-in-every-service.md` | ADR-0017, plus its row in `docs/adr/README.md`. |
| `docs/steps/step-17-jwt-auth-on-the-apis.md` | This write-up, plus its row in `docs/steps/README.md`, the changelog entry and 21 new glossary terms. |

## Notes for this repository

- **`read_only: true` is not in the Compose service.** Current Docker Compose (v5.6 was used
  here) refuses to start a read-only service whose secrets come from environment variables:
  `cannot create secret "step17live_rag_api_gateway_key" in read-only service rag-api: "file" is the sole supported option`.
  That was reproduced here with the guide's exact service definition. Switching to `file:` secrets would put
  decrypted values on disk, against Step 6. The service therefore keeps every other hardening setting, and the
  image keeps `/app` owned by root while the process runs as uid 10001: in the running container `id` printed
  `uid=10001(app)`, writing to `/app` and to the installed code failed with `Permission denied`, `/tmp` (tmpfs) was
  writable, and all capability sets were zero. The compose file explains this in a comment, and the test asserts
  it.
- **The base images are pinned by real digests.** The guide asks you to pin both `FROM` images with
  `docker buildx imagetools inspect`. `ghcr.io/astral-sh/uv:0.11.32` is
  `sha256:df4cae8f…504c` and `python:3.12-slim-bookworm` is `sha256:34386ef0…7258` (index digests, looked up on
  2026-10-12; the Docker Hub copy `astral/uv:0.11.32` has the same digest). Re-check them on your Mac before the
  first build, and refresh them when you want security updates.
- **The verifier's key cache has a 30-second cool-down.** PyJWT 2.15 (the locked version) only re-fetches the JWKS
  for an unknown `kid` once per 30 s. The guide's code is unchanged; the behaviour is documented above and tested
  in `libs/rag-common/tests/test_auth_verifier.py`.
- **Small, faithful code adjustments.** The `client` fixture in `test_auth.py` is typed `Iterator[TestClient]`
  (it `yield`s) so strict mypy accepts it; `get_settings()` needs no `# type: ignore` with the pydantic mypy
  plugin; `scripts/api_demo.py` puts its calls in `main()` (as the Step 16 scripts do), so tests can import it, with
  the signature forging in a small `forge()` helper. mypy now also checks `services/rag-api/tests`. The root
  `pyproject.toml` keeps the existing `scripts` and `tests` entries next to the guide's new mypy paths.
- **Extra tests beyond the guide's 21.** `services/rag-api/tests/test_service.py` (7 tests),
  `libs/rag-common/tests/test_auth_verifier.py` (10) and `tests/test_rag_api.py` (13 static + 4 live). The guide's
  `test_auth.py` still reports exactly `21 passed` on its own.
- **What was validated here (Linux container with Docker, no Mac, no SOPS key).** `uv sync --all-packages`, ruff,
  strict mypy (40 files) and the whole test suite pass. The image was built from this Dockerfile (pulling the same
  digests through `mirror.gcr.io`, with the build container trusting the sandbox's HTTPS proxy; neither change is in
  the committed file) and run with this Compose file next to the real Keycloak 26.8.0 (same digest), `keycloak-db`
  and `rag-db`, with random test secrets. The Step 11 migration was applied and `scripts/pg_demo.py` loaded the four
  demo documents; LiteLLM was replaced by a tiny OpenAI-compatible stand-in, because the embedding model only runs
  natively on a Mac. Results: `rag-api` became **healthy**; `/healthz` → 200; `/v1/me` without a token → 401 with
  `www-authenticate: Bearer realm="rag-api"`. Users were provisioned with `scripts/kc_users.py`, and the device
  sign-in in `scripts/api_demo.py` was approved by a small helper. `just api-demo`'s script printed, as alice:
  `/v1/me` 200 (`all-staff`, `engineering`), search 200 with Parking and Remote work policy only, admin ping 403,
  machine `/v1/me` 200 as `service-account-ingestion-worker`, machine search 403, no token 401, forged token 401
  (logged as `rejected token: InvalidSignatureError`); as carol, the search also returned **Exec offsite**; as dave,
  admin ping returned **200**. The gateway stand-in received `user=<sub>` for each person's embedding call. Adding
  a new, higher-priority RS256 key in Keycloak (key rotation) gave tokens with a new `kid` that rag-api accepted at
  once, while tokens signed with the old key kept working. With Keycloak stopped, a running rag-api still accepted
  tokens from its key cache (200); after restarting rag-api (empty cache) the same token got **503** "Identity
  provider unavailable", and a garbage token still got 401. The live tests in `tests/test_rag_api.py` and
  `tests/test_keycloak.py` passed against that stack (42 tests). The test stack, its volumes and the images were
  removed afterwards.
