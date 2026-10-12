# Step 16 · Keycloak: realm, users and groups

*Step 16 of 38 · Phase D · Identity & policy*

## At a glance

| | |
|---|---|
| **Goal** | Give the platform one place that knows who everyone is. People and machines sign in to Keycloak, an open-source identity server. Keycloak hands each of them a signed token that says who they are, which groups they belong to and which roles they hold. Later steps use that token to protect the APIs (Step 17) and to filter documents (Step 18). |
| **Time** | About 90 minutes. |
| **You'll end up with** | `keycloak` (26.8.x, pinned) and its own database `keycloak-db`, on `127.0.0.1:8180`; a realm `rag` defined as code in a JSON file (password policy, lockout, short token lifetimes, login and admin event logging); groups that match the documents' `acl_groups` from Step 11, with roles attached to groups; four apps (clients): a web app, a command-line app, an API and an ingestion worker (plus a provisioning client); demo users created by a least-privilege provisioning account, with MFA required for admins; a terminal sign-in using the device flow, a machine sign-in using client credentials, and a look inside the tokens; your own permanent admin with MFA, replacing the temporary one; ADR-0016. |
| **New words** | Identity provider (IdP), authentication vs authorisation, realm, OpenID Connect (OIDC), OAuth 2.0, client (public / confidential), grant / flow, authorization code + PKCE, device flow, client credentials, access / ID / refresh token, claim, issuer, audience, JWKS, group, realm role, protocol mapper, client scope, SSO session, required action, MFA / TOTP, brute-force protection, service account, bootstrap admin, events. |

## The big idea

> **ANALOGY · THE BADGE OFFICE**
> A big office building doesn't make every door guard memorise every employee. There is one badge office at
> the entrance:
>
> - You prove who you are once, at the badge office (sign in).
> - You get a badge with your photo, your department and an expiry date, printed on paper that is hard to forge
>   (a signed token).
> - Each door only checks the badge: is it real, is it still valid, does this department get in? (APIs verify the
>   token, Step 17.)
> - Which rooms a department may enter is a separate rulebook (policy, Step 18).
> - Delivery robots get badges too, through a separate desk with their own keys (service accounts).
>
> Keycloak is the badge office. When someone leaves the company, you cancel them in one place and every
> door stops letting them in.

```text
  People                                                              rag-web · rag-cli
  alice · engineering        1 sign in      Keycloak · realm rag      apps people use
  bob · hr               ───────────────►   users · groups · roles        │
  carol · executives                        clients · client scopes       │ 3 Bearer token
  dave · platform-admins     2 token        password policy · MFA ·       ▼
                         ◄───────────────   lockout                    rag-api
  Machines                                  login + admin events       verifies the token (Step 17)
  ingestion-worker           1 secret       (audit)                       │ 4 groups
  (service account)      ───────────────►   checks who you are →          ▼
                                            signs a token              Postgres filter
                                                                       acl_groups && groups (Step 18)

  One place decides who someone is. Every app trusts Keycloak's signature instead of keeping its own passwords.
```

*Figure 50. The identity picture. People and machines prove who they are to Keycloak once; it signs a token with
their groups and roles; apps send that token to the API, which checks it and uses the groups to filter documents.*

## What we're doing

1. Add secrets: database password, two client secrets (the admin password exists since Step 6).
2. Run `keycloak-db` (Postgres) and `keycloak` in Compose, in production mode, with health checks.
3. Write the realm `rag` as a JSON file: security settings, roles, groups, clients, service accounts. Keycloak
   imports it on first start.
4. Replace the temporary admin with your own admin account protected by MFA.
5. Create demo users with a least-privilege provisioning script.
6. Sign in as a person (device flow) and as a machine (client credentials) and read the tokens.
7. Test lockout and look at the event log.
8. Record ADR-0016.

## Why we're doing this

> **WHY THIS MATTERS**
> So far every caller is identified by a shared key: the gateway knows "the RAG API" called, but not which person
> asked. Permission-aware RAG needs to know who the user is and which groups they're in, on every single
> question. Step 11 hard-coded `["all-staff"]`; that has to come from a real sign-in. Building logins yourself
> (password storage, lockout, MFA, password reset, single sign-on, auditing) is a large, risky project. An identity
> server does it properly and is what every enterprise expects.

| Need | How Keycloak meets it |
|---|---|
| Know which person is asking | OIDC sign-in, signed access tokens with a stable user id |
| Retrieval permissions | A `groups` claim matching `acl_groups` on documents |
| What someone may do (admin, audit) | Realm roles, attached to groups |
| Machines (ingestion, evaluation) | Service accounts with client credentials |
| Strong sign-in | Password policy, MFA (TOTP), brute-force lockout |
| Sign in once for every app | SSO session shared across clients |
| Leaver removed everywhere at once | Disable one user; short token lifetimes do the rest |
| "Who changed what?" | Login events and admin events (feeds the audit log, Step 23) |
| Later: company accounts | Federation with Active Directory / LDAP or brokering to Entra ID, Okta, Google |

> **IN A COMPANY**
> Identity is usually owned by a security or IAM team, and they'll ask three things:
>
> - **Joiner, mover, leaver:** how are accounts created, changed and removed?
> - **Access reviews:** who can approve and see who has what?
> - **Audit trail:** where are sign-ins and admin changes logged?
>
> Good answers are: accounts come from the corporate directory (federation, or SCIM, which Keycloak 26.8 now
> supports); access goes through groups, never one-off grants; and events are kept and shipped to the audit log.
> Many companies already use Entra ID or Okta. Keycloak then sits in front of the RAG platform as a broker, so
> the platform's own setup stays the same.

## Key ideas

| Term | Plain-English meaning |
|---|---|
| **Authentication vs authorisation** | Who are you? (sign-in) vs what may you do? (permissions). Keycloak does the first and carries facts for the second. |
| **Identity provider (IdP)** | The service that signs people in and vouches for them: Keycloak here. |
| **Realm** | A separate, self-contained space in Keycloak with its own users, groups, apps and settings. `master` is only for running Keycloak itself; our apps use `rag`. |
| **OAuth 2.0 / OpenID Connect (OIDC)** | The standards for getting tokens. OAuth 2.0 covers access; OIDC adds identity (who signed in) on top. |
| **Client** | An app registered with Keycloak. Public clients (browser, CLI) can't keep a secret; confidential clients (servers) can. |
| **Grant / flow** | A recipe for getting a token: authorization code + PKCE (web apps), device flow (CLIs, TVs), client credentials (machines). |
| **Access / ID / refresh token** | Access: shown to APIs, short-lived (5 min). ID: tells the app who signed in. Refresh: swaps for new access tokens without signing in again. |
| **JWT and claims** | The token format: three Base64 parts (header, payload, signature). Each field in the payload is a claim. |
| **Issuer (`iss`) / audience (`aud`)** | Who made the token / who it is meant for. An API must reject tokens meant for someone else. |
| **JWKS** | The public keys Keycloak publishes so anyone can check its signatures. |
| **Group / realm role** | Group: who you are with (department, team), which decides what you see. Role: what you may do. |
| **Protocol mapper / client scope** | A mapper puts extra facts (like `groups`) into tokens. A client scope bundles mappers to share between clients. |
| **SSO session** | Your sign-in at Keycloak itself. While it lasts, other apps sign you in without asking again. |
| **Required action** | Something a user must do at next sign-in: change password, set up MFA, verify email. |
| **MFA / TOTP** | A second proof besides the password. TOTP is the six-digit code from an authenticator app. |
| **Brute-force protection** | Temporarily locking an account after several wrong passwords. |
| **Service account** | A non-human identity tied to a confidential client, used with client credentials. |
| **Bootstrap (temporary) admin** | The first admin created at start-up, to be replaced by a real, MFA-protected admin. |
| **Events** | Keycloak's own log of sign-ins and failures (login events) and of every administrative change (admin events). |

### Users, groups and roles

```text
  Users                    Groups · what you can SEE         Realm roles · what you can DO

  alice ─────────────────► all-staff + engineering
  bob   ─────────────────► all-staff + hr
  carol ─────────────────► all-staff + executives
  dave  ─────────────────► all-staff + platform-admins
  erin  ─────────────────► all-staff + auditors

                           all-staff ──────────────────────► rag-user
                           engineering, hr, executives        (no role: they decide what you SEE)
                           platform-admins ────────────────► rag-admin
                           auditors ───────────────────────► rag-auditor

  ingestion-worker (service account, no groups) ───────────► rag-ingest

  Users join groups; groups carry roles. Nobody gets a role directly, so access is reviewed in one place.
  Group names match the acl_groups on documents (Step 11): that is how sign-in becomes retrieval permissions.
```

*Figure 51. How access is organised. Users join groups; groups carry roles. Group names match the documents'
access groups, which is how a sign-in becomes retrieval permissions. Machines get roles through their service
account.*

> **WHY GROUPS FIRST, ROLES SECOND**
> Two questions, two tools:
>
> - **What may I see?** That depends on who you are with: HR sees HR documents. That's a group, and it's
>   copied into the token's `groups` claim for document filtering.
> - **What may I do?** For example, manage collections or read audit logs. That's a role.
>
> Roles are attached to groups, never given straight to a person. When Dave moves from `platform-admins` to
> `engineering`, one membership change updates everything. An access review is then a short list of groups, not a
> thousand individual grants.

### What's inside a token

```text
  eyJhbGciOiJSUzI1NiIs… . eyJpc3MiOiJodHRwOi8vbG9jYWxo… . SflKxwRJSMeKKF2QT4fw…

  HEADER                  PAYLOAD · the claims                           SIGNATURE
  alg RS256               iss  http://localhost:8180/realms/rag          made with Keycloak's PRIVATE key
  typ JWT                 aud  rag-api                                   checked with the PUBLIC key
  kid 9Xc2…               azp  rag-cli (app that asked)                  from …/certs (JWKS)
                          sub  8f1c… (stable user id)
  which key signed it,    preferred_username alice                       change one letter →
  so the API can pick     groups [all-staff, engineering]                signature fails
  the right public key    realm_access.roles [rag-user]
                          exp  issued + 5 minutes

  Anyone can READ a token (it's only Base64). Only Keycloak can SIGN one. Never put secrets in claims.
```

*Figure 52. A JWT has three parts. The header names the signing key; the payload holds the claims (issuer,
audience, user, groups, roles, expiry); the signature proves Keycloak made it and nothing was changed.*

> **WATCH OUT · READABLE IS NOT THE SAME AS TRUSTED**
> Anyone holding a token can decode it; it is not encrypted. This step decodes tokens just to look at them.
> Trusting a token means checking the signature against Keycloak's public keys, plus the issuer, audience and
> expiry. That is Step 17's job; never skip it in an API.

### How a terminal signs you in

```text
  rag-cli (your terminal)                    Keycloak                       You, in a browser
         │ 1 POST …/auth/device (client_id=rag-cli) ─►│
         │◄─ 2 device_code + user code + link ────────│
         │ 3 shows you the link and code ─────────────────────────────────────►│
         │                                            │◄─ 4 you log in (password + MFA) and approve
         │ 5 polls …/token every 5 s ────────────────►│
         │◄─ 6 access token + refresh token ──────────│

  The terminal never sees your password, and MFA works. It's how you sign in to a TV app with your phone.
```

*Figure 53. The device flow. The command-line app asks Keycloak for a code, shows you a link, and waits. You sign
in with your password and MFA in the browser; the app then receives its tokens without ever seeing your
password.*

> **WATCH OUT · WHY NOT JUST TYPE THE PASSWORD INTO THE SCRIPT?**
> That shortcut (the "password grant", formally ROPC) exists, but modern OAuth guidance says don't use it:
>
> - The app sees your password.
> - MFA can't work.
> - It trains people to type passwords into random tools.
>
> It is switched off on every client in our realm. Browser apps use authorization code + PKCE, terminals use the
> device flow, and machines use client credentials.

## How to do it

All commands run from the repository root (`~/dev/rag-platform` on your Mac). The guide works on a branch:

```bash
cd ~/dev/rag-platform
git switch -c feat/keycloak
```

### 1 · Secrets

```bash
for i in 1 2 3; do openssl rand -base64 48 | tr -d '/+=\n' | cut -c1-32; echo; done
just secrets-edit
#   keep KEYCLOAK_ADMIN_PASSWORD (Step 6), then add:
#   KEYCLOAK_DB_PASSWORD=<1st>   KEYCLOAK_PROVISIONER_SECRET=<2nd>   KEYCLOAK_INGESTION_SECRET=<3rd>
```

Then update `.env.example` and `scripts/new-dev-secrets.sh` to match. In this repository both are done: the
generator now writes `KEYCLOAK_DB_PASSWORD`, `KEYCLOAK_PROVISIONER_SECRET` and `KEYCLOAK_INGESTION_SECRET` next to
`KEYCLOAK_ADMIN_PASSWORD`, all with the same `rand` helper (32 letters/digits), and `.env.example` lists the four
names with what each one is for.

### 2 · Write the realm as code

Every setting lives in one reviewed file, so a fresh machine gets an identical realm. It holds no secrets: the two
client secrets are `${…}` placeholders that Keycloak fills from environment variables when it imports the file.

File `infra/config/keycloak/realm-rag.json`:

```json
{
  "realm": "rag",
  "displayName": "RAG Platform",
  "enabled": true,
  "sslRequired": "external",
  "registrationAllowed": false,
  "resetPasswordAllowed": false,
  "loginWithEmailAllowed": true,
  "duplicateEmailsAllowed": false,
  "editUsernameAllowed": false,

  "passwordPolicy": "length(12) and maxLength(128) and notUsername and notEmail and passwordHistory(5)",
  "bruteForceProtected": true,
  "failureFactor": 5,
  "waitIncrementSeconds": 60,
  "maxFailureWaitSeconds": 900,
  "permanentLockout": false,

  "accessTokenLifespan": 300,
  "ssoSessionIdleTimeout": 1800,
  "ssoSessionMaxLifespan": 36000,
  "revokeRefreshToken": true,
  "refreshTokenMaxReuse": 0,

  "eventsEnabled": true,
  "eventsExpiration": 2592000,
  "adminEventsEnabled": true,
  "adminEventsDetailsEnabled": true,

  "roles": {
    "realm": [
      { "name": "rag-user",    "description": "May ask questions of the RAG platform" },
      { "name": "rag-admin",   "description": "Manages collections and platform settings" },
      { "name": "rag-auditor", "description": "Reads audit logs, nothing else" },
      { "name": "rag-ingest",  "description": "Machine role: may submit and process documents" }
    ]
  },
  "groups": [
    { "name": "all-staff",       "realmRoles": ["rag-user"] },
    { "name": "engineering" },
    { "name": "hr" },
    { "name": "executives" },
    { "name": "platform-admins", "realmRoles": ["rag-admin"] },
    { "name": "auditors",        "realmRoles": ["rag-auditor"] }
  ],
  "defaultGroups": ["/all-staff"],

  "clients": [
    { "clientId": "rag-api", "name": "RAG API (audience only, never signs anyone in)",
      "bearerOnly": true, "standardFlowEnabled": false, "directAccessGrantsEnabled": false },
    { "clientId": "rag-web", "name": "RAG web app", "publicClient": true,
      "standardFlowEnabled": true, "implicitFlowEnabled": false, "directAccessGrantsEnabled": false,
      "redirectUris": ["http://localhost:3000/*"], "webOrigins": ["http://localhost:3000"],
      "attributes": { "pkce.code.challenge.method": "S256", "post.logout.redirect.uris": "http://localhost:3000/*" },
      "protocolMappers": [ "audience-rag-api (oidc-audience-mapper)", "groups (oidc-group-membership-mapper)" ] },
    { "clientId": "rag-cli", "name": "RAG command-line tool", "publicClient": true,
      "standardFlowEnabled": false, "directAccessGrantsEnabled": false,
      "attributes": { "oauth2.device.authorization.grant.enabled": "true" },
      "protocolMappers": [ "the same two mappers" ] },
    { "clientId": "ingestion-worker", "name": "Ingestion worker (machine)", "publicClient": false,
      "secret": "${KEYCLOAK_INGESTION_SECRET}", "serviceAccountsEnabled": true,
      "standardFlowEnabled": false, "directAccessGrantsEnabled": false,
      "protocolMappers": [ "audience-rag-api only" ] },
    { "clientId": "rag-provisioner", "name": "User provisioning automation", "publicClient": false,
      "secret": "${KEYCLOAK_PROVISIONER_SECRET}", "serviceAccountsEnabled": true,
      "standardFlowEnabled": false, "directAccessGrantsEnabled": false }
  ],
  "users": [
    { "username": "service-account-ingestion-worker", "enabled": true,
      "serviceAccountClientId": "ingestion-worker", "realmRoles": ["rag-ingest"] },
    { "username": "service-account-rag-provisioner", "enabled": true,
      "serviceAccountClientId": "rag-provisioner",
      "clientRoles": { "realm-management": ["manage-users", "view-users", "query-users", "query-groups"] } }
  ]
}
```

(The `clients` block above is shortened for reading; the committed file spells out each mapper in full. The two
mappers are:)

```json
{ "name": "audience-rag-api", "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper",
  "config": { "included.client.audience": "rag-api", "access.token.claim": "true", "id.token.claim": "false" } },
{ "name": "groups", "protocol": "openid-connect", "protocolMapper": "oidc-group-membership-mapper",
  "config": { "claim.name": "groups", "full.path": "false", "access.token.claim": "true",
              "id.token.claim": "true", "userinfo.token.claim": "true" } }
```

> **IN PLAIN ENGLISH · READING THE REALM FILE, SECTION BY SECTION**
>
> - **Sign-in rules:** no self-registration (accounts are created deliberately); no password reset yet (there's no
>   mail server); `sslRequired: external` allows plain HTTP only from local addresses.
> - **Passwords and lockout:** at least 12 characters, can't be your username or email, can't reuse the last 5.
>   After 5 wrong attempts the account waits 60 s, growing up to 15 minutes. It's temporary
>   (`permanentLockout: false`), so an attacker can't lock everyone out for good.
> - **Lifetimes:** access tokens live 5 minutes. The Keycloak session ends after 30 idle minutes or 10 hours in
>   total. Refresh tokens are one-time use (`revokeRefreshToken`), so a stolen, already-used one is useless.
> - **Events:** sign-ins and failures are kept 30 days; every admin change is recorded with details.
> - **Roles and groups:** as in the diagram. `defaultGroups` puts any new user into `all-staff` automatically.
> - **Clients:**
>   - `rag-api` only exists to be an audience: it never signs anyone in.
>   - `rag-web` and `rag-cli` are public, use PKCE / device flow, and get two mappers: one adds `rag-api` to `aud`,
>     the other adds the `groups` claim with plain names (`full.path: false` gives `hr` instead of `/hr`).
>   - `ingestion-worker` and `rag-provisioner` are confidential machine clients.
> - **Service accounts:** the worker gets only `rag-ingest`. The provisioner may manage users only (not clients,
>   not realm settings): least privilege for automation.

> **TIP · SHARING MAPPERS**
> `rag-web` and `rag-cli` repeat the same two mappers. With many clients, you'd put them in a client scope
> once and attach it to each client. We keep them inline so the file is self-explanatory.

### 3 · Run Keycloak and its database

Check the current release (26.8.0, published 1 October 2026; see Keycloak's GitHub releases) and pin its digest:

```bash
docker buildx imagetools inspect quay.io/keycloak/keycloak:26.8.0 | head -5
```

The two new services in `infra/compose/compose.yaml` (added after `valkey`):

```yaml
services:
  keycloak-db:
    image: postgres:17-alpine@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24
    environment:
      POSTGRES_DB: keycloak
      POSTGRES_USER: keycloak
      POSTGRES_PASSWORD_FILE: /run/secrets/keycloak_db_password
    secrets: [keycloak_db_password]
    volumes:
      - keycloak-db-data:/var/lib/postgresql/data
    # no "ports:": only Keycloak needs it
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U keycloak -d keycloak"]
      interval: 10s
      timeout: 5s
      retries: 10
    restart: unless-stopped
    security_opt: ["no-new-privileges:true"]
    deploy:
      resources:
        limits: { memory: 512m, cpus: "1" }

  keycloak:
    image: quay.io/keycloak/keycloak:26.8.0@sha256:27b3230fbabb8c9ff3c66c864cf09dcd8a41aca82e5100679d109ef0eeb05741
    entrypoint: ["/bin/bash", "-c"]
    command:
      - |
        export KC_BOOTSTRAP_ADMIN_PASSWORD="$$(cat /run/secrets/keycloak_admin_password)"
        export KC_DB_PASSWORD="$$(cat /run/secrets/keycloak_db_password)"
        export KEYCLOAK_INGESTION_SECRET="$$(cat /run/secrets/keycloak_ingestion_secret)"
        export KEYCLOAK_PROVISIONER_SECRET="$$(cat /run/secrets/keycloak_provisioner_secret)"
        exec /opt/keycloak/bin/kc.sh start --import-realm
    environment:
      KC_DB: postgres
      KC_DB_URL: jdbc:postgresql://keycloak-db:5432/keycloak   # no password here (KC_DB_PASSWORD); gitleaks:allow
      KC_DB_USERNAME: keycloak
      KC_HOSTNAME: http://localhost:8180              # the one public address; becomes the token issuer
      KC_HOSTNAME_BACKCHANNEL_DYNAMIC: "true"         # containers may call it as http://keycloak:8080
      KC_HTTP_ENABLED: "true"                         # plain HTTP only because it's bound to 127.0.0.1
      KC_HEALTH_ENABLED: "true"                       # /health/* on management port 9000
      KC_METRICS_ENABLED: "true"                      # /metrics on port 9000, for Prometheus (Step 20)
      KC_CACHE: local                                 # single node; clustering comes with Kubernetes
      KC_LOG_CONSOLE_OUTPUT: json                     # structured logs, for Loki (Step 21)
      KC_BOOTSTRAP_ADMIN_USERNAME: temp-admin         # used only on the very first start
    secrets: [keycloak_admin_password, keycloak_db_password, keycloak_ingestion_secret,
              keycloak_provisioner_secret]
    volumes:
      - ../config/keycloak/realm-rag.json:/opt/keycloak/data/import/realm-rag.json:ro
    ports:
      - "127.0.0.1:8180:8080"                         # 9000 (health/metrics) is NOT published
    depends_on:
      keycloak-db: { condition: service_healthy }
    healthcheck:
      # the image has no curl; bash talks HTTP to the readiness endpoint directly
      test: ["CMD", "bash", "-c", "{ printf 'HEAD /health/ready HTTP/1.0\\r\\n\\r\\n' >&0; grep -q 'HTTP/1.0 200'; } 0<>/dev/tcp/localhost/9000"]
      interval: 15s
      timeout: 5s
      retries: 10
      start_period: 60s
    restart: unless-stopped
    security_opt: ["no-new-privileges:true"]
    deploy:
      resources:
        limits: { memory: 1536m, cpus: "2" }

volumes:
  keycloak-db-data:

secrets:
  keycloak_admin_password:     { environment: KEYCLOAK_ADMIN_PASSWORD }
  keycloak_db_password:        { environment: KEYCLOAK_DB_PASSWORD }
  keycloak_ingestion_secret:   { environment: KEYCLOAK_INGESTION_SECRET }
  keycloak_provisioner_secret: { environment: KEYCLOAK_PROVISIONER_SECRET }
```

As with LiteLLM, Qdrant and OpenSearch, Keycloak only reads its passwords from environment variables, so a tiny
`bash` wrapper reads the secret **files** and exports them inside the container process only; they never appear in
`docker inspect`. The two client secrets are exported under the exact names the realm file's `${…}` placeholders
use, which is how the import fills them in.

> **IN PLAIN ENGLISH · PRODUCTION MODE ON A LAPTOP**
> We use `start` (production mode), not `start-dev`, so we learn the real settings: a fixed hostname, a real
> database and health checks. The only dev shortcut is plain HTTP, which is safe here because the port is bound
> to `127.0.0.1`. In production, Keycloak sits behind TLS (Step 37).
>
> `KC_HOSTNAME` matters more than it looks. It fixes the issuer written into every token as
> `http://localhost:8180/realms/rag`, whichever address you used to reach Keycloak. APIs check this value.
> `KC_HOSTNAME_BACKCHANNEL_DYNAMIC` lets containers fetch keys and tokens over the internal address
> `keycloak:8080` while tokens keep that single issuer. Step 17 relies on both.

> **WATCH OUT · THE REALM FILE IS IMPORTED ONCE**
> `--import-realm` imports a realm only if it doesn't exist yet. Later edits to the JSON are ignored on restart, so
> the file and the running realm can drift apart. For now, after changing the file in dev, reset Keycloak's
> database: `just down`, then `docker volume rm rag-platform_keycloak-db-data`, then `just up`, and re-run
> `just kc-users`. That deletes all users and sessions, which is fine only in dev.
>
> Teams keep realms in sync continuously with keycloak-config-cli or the Terraform Keycloak provider, which
> apply only the differences. Revisit this in Phase G.

Two new recipes in the `justfile`:

```text
# Keycloak
kc-users:
    just with-secrets uv run --with httpx scripts/kc_users.py
kc-whoami:
    just with-secrets uv run --with httpx scripts/kc_whoami.py
```

Start the stack and look at the realm:

```bash
just up && just ps                 # keycloak becomes healthy after ~30-60 s
docker compose -f infra/compose/compose.yaml logs keycloak | grep -i -E "import|started"
curl -s http://localhost:8180/realms/rag/.well-known/openid-configuration | jq '{issuer, token_endpoint, jwks_uri}'
```

The last command shows the realm's **discovery document**: every address an app needs, in one place. Apps are
configured with just the issuer URL and find the rest here. You should see:

```json
{
  "issuer": "http://localhost:8180/realms/rag",
  "token_endpoint": "http://localhost:8180/realms/rag/protocol/openid-connect/token",
  "jwks_uri": "http://localhost:8180/realms/rag/protocol/openid-connect/certs"
}
```

The logs show `Realm 'rag' imported` on the first start and `Realm 'rag' already exists. Import skipped` on every
start after that.

### 4 · Replace the temporary admin

The first start created `temp-admin` in the `master` realm. The console flags it as temporary, and it should exist
only long enough to create a real admin.

1. Open <http://localhost:8180/admin/> and sign in as `temp-admin` (its password is `KEYCLOAK_ADMIN_PASSWORD`: run
   `just secrets-edit` to read it, then close without saving).
2. Stay in realm **master** → **Users** → **Add user**: your own username and email → **Create**.
3. **Credentials** → **Set password** (Temporary: off). **Role mapping** → **Assign role** → filter by realm roles →
   **admin**.
4. **Details** → **Required user actions** → **Configure OTP** → **Save**.
5. Sign out, then sign in as yourself. Scan the QR code with an authenticator app (1Password, Google
   Authenticator, Authy…).
6. **Users** → `temp-admin` → **Delete**.

> **WATCH OUT · KEEP MASTER FOR ADMINISTRATORS ONLY**
> No application ever signs users in through `master`. Our apps use `rag`. If the `rag` realm were misconfigured,
> the separation means an app user still can't become a Keycloak administrator.

### 5 · Create demo users, with least privilege

Users are data, not configuration, so they're kept out of the realm file. In a company they would come from the
directory (LDAP/AD or SCIM). Here, a script creates them using the `rag-provisioner` service account, which can
manage users and nothing else.

File `scripts/kc_users.py` (the guide's code, wrapped in a `main()` function):

```python
KC, REALM = "http://127.0.0.1:8180", "rag"
USERS = [  # username, first name, groups, MFA required
    ("alice", "Alice", ["all-staff", "engineering"], False),
    ("bob", "Bob", ["all-staff", "hr"], False),
    ("carol", "Carol", ["all-staff", "executives"], False),
    ("dave", "Dave", ["all-staff", "platform-admins"], True),
    ("erin", "Erin", ["all-staff", "auditors"], True),
]

def main() -> None:
    # 1. The script signs in as a MACHINE (client credentials): no human password involved
    token = httpx.post(f"{KC}/realms/{REALM}/protocol/openid-connect/token", data={
        "grant_type": "client_credentials", "client_id": "rag-provisioner",
        "client_secret": os.environ["KEYCLOAK_PROVISIONER_SECRET"]}).raise_for_status().json()["access_token"]
    api = httpx.Client(base_url=f"{KC}/admin/realms/{REALM}", headers={"Authorization": f"Bearer {token}"})

    group_ids = {g["name"]: g["id"] for g in api.get("/groups", params={"max": 100}).raise_for_status().json()}

    for username, first, groups, mfa in USERS:
        found = api.get("/users", params={"username": username, "exact": "true"}).raise_for_status().json()
        if found:
            uid, status = found[0]["id"], "already exists"
        else:
            password = secrets.token_urlsafe(12)  # 16 random characters, shown once
            r = api.post("/users", json={
                "username": username, "firstName": first, "lastName": "Demo",
                "email": f"{username}@example.com", "emailVerified": True, "enabled": True,
                "requiredActions": ["CONFIGURE_TOTP"] if mfa else [],
                "credentials": [{"type": "password", "value": password, "temporary": True}],
            })
            r.raise_for_status()
            uid = r.headers["Location"].rsplit("/", 1)[-1]
            status = f"created · one-time password: {password}"
        for g in groups:  # PUT is idempotent: safe to repeat
            api.put(f"/users/{uid}/groups/{group_ids[g]}").raise_for_status()
        print(f"{username:6} {', '.join(groups):30} {status}")

    # 2. Least-privilege proof: the provisioner can't read the realm's apps (and their secrets)
    print("provisioner -> list clients:", api.get("/clients").status_code, "(403 expected)")
```

```bash
just kc-users
```

> **WHAT YOU SHOULD SEE**
> Five users with their groups, each with a one-time password. Copy alice's and carol's now; the script never
> shows them again.
>
> - `temporary: True` forces a new password at first sign-in, so the script's copy is useless afterwards.
>   Dave and Erin must also set up MFA first.
> - The last line prints `403`: the provisioning account can't even list the realm's clients. If its secret leaked,
>   the damage would be limited to user accounts.
>
> Run the script a second time: every user says "already exists" and nothing changes. That's idempotency again.

```text
alice  all-staff, engineering         created · one-time password: …
bob    all-staff, hr                  created · one-time password: …
carol  all-staff, executives          created · one-time password: …
dave   all-staff, platform-admins     created · one-time password: …
erin   all-staff, auditors            created · one-time password: …
provisioner -> list clients: 403 (403 expected)
```

### 6 · Sign in, and look inside the tokens

File `scripts/kc_whoami.py` signs in from the terminal (device flow), signs in as a machine (client credentials),
looks inside both tokens, then signs out:

```python
OIDC = "http://127.0.0.1:8180/realms/rag/protocol/openid-connect"

def claims(jwt: str) -> dict[str, Any]:
    """Decode the payload WITHOUT checking the signature. Fine for looking; never for trusting (Step 17)."""
    part = jwt.split(".")[1]
    payload: dict[str, Any] = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    return payload

# --- 1. a PERSON, via the device flow ---
d = httpx.post(f"{OIDC}/auth/device", data={"client_id": "rag-cli", "scope": "openid"}).raise_for_status().json()
print(f"Open {d['verification_uri_complete']}\n  (or {d['verification_uri']} and enter {d['user_code']})")
while True:
    time.sleep(d.get("interval", 5))
    r = httpx.post(f"{OIDC}/token", data={"grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                                          "client_id": "rag-cli", "device_code": d["device_code"]})
    if r.status_code == 200:
        break
    if r.json().get("error") not in ("authorization_pending", "slow_down"):
        r.raise_for_status()
person = r.json()
show("PERSON · access token", claims(person["access_token"]))

# --- 2. a MACHINE, via client credentials ---
m = httpx.post(f"{OIDC}/token", data={"grant_type": "client_credentials", "client_id": "ingestion-worker",
               "client_secret": os.environ["KEYCLOAK_INGESTION_SECRET"]}).raise_for_status().json()
show("MACHINE · access token", claims(m["access_token"]))
print("  machine got a refresh token?", "refresh_token" in m)

# --- 3. sign the person out: ends the Keycloak session and kills the refresh token ---
httpx.post(f"{OIDC}/logout", data={"client_id": "rag-cli", "refresh_token": person["refresh_token"]}).raise_for_status()
r = httpx.post(f"{OIDC}/token", data={"grant_type": "refresh_token", "client_id": "rag-cli",
                                      "refresh_token": person["refresh_token"]})
print("\nrefresh after logout ->", r.status_code, r.json().get("error"))
```

(`show()` prints `iss`, `aud`, `azp`, `sub`, `preferred_username`, `groups`, `realm_access`, `scope` and the seconds
until expiry.)

```bash
just kc-whoami
```

Open the printed link in a private browser window and sign in as alice with her one-time password. Keycloak makes
you choose a new one. Approve the request, then look back at the terminal.

> **WHAT YOU SHOULD SEE**
>
> - **PERSON:**
>   - `iss`: `http://localhost:8180/realms/rag`
>   - `aud`: includes `rag-api` (you may also see `account`, Keycloak's self-service app)
>   - `azp`: `rag-cli`
>   - `preferred_username`: `alice`
>   - `groups`: `['all-staff', 'engineering']`
>   - roles: include `rag-user`, which came from the group
>   - expiry: about 300 s
> - **MACHINE:** `azp` is `ingestion-worker`, the username is `service-account-ingestion-worker`, it has the role
>   `rag-ingest` and no groups. It also gets no refresh token: a machine simply asks again with its secret.
> - **After logout:** the old refresh token fails with `400 invalid_grant`. Signing out really ends the session.
>
> Run it again and sign in as carol. Her `groups` claim shows `executives`. That is exactly the value Step 11's
> search filter needs, now coming from a real sign-in instead of a hard-coded list.

This is the actual output from this repository's test run (alice signed in through the device page):

```text
PERSON · access token
  iss                 http://localhost:8180/realms/rag
  aud                 ['rag-api', 'account']
  azp                 rag-cli
  sub                 7399a834-a10a-49ec-a101-dfd27d252073
  preferred_username  alice
  groups              ['all-staff', 'engineering']
  realm_access        {'roles': ['rag-user', 'offline_access', 'default-roles-rag', 'uma_authorization']}
  scope               openid profile email
  expires in          300 s

MACHINE · access token
  iss                 http://localhost:8180/realms/rag
  aud                 rag-api
  azp                 ingestion-worker
  sub                 c664fcab-02f4-44d9-a182-67f40019e877
  preferred_username  service-account-ingestion-worker
  realm_access        {'roles': ['rag-ingest']}
  scope               profile email
  expires in          300 s
  machine got a refresh token? False

refresh after logout -> 400 invalid_grant
```

### 7 · Test the lockout, and read the event log

1. In a private window, open <http://localhost:8180/realms/rag/account> and enter a wrong password for bob five
   times.
2. Now try his correct password. You're refused, and the message doesn't say why (attackers learn nothing).
3. In the admin console, switch to realm **rag**:
   - **Users** → bob shows he's temporarily locked. An admin can unlock him early.
   - **Events** → **User events**: one `LOGIN_ERROR` per attempt, each with time, IP and client.
   - **Events** → **Admin events**: every user the provisioner created, with the full details.

> **IN A COMPANY · EVENTS ARE AUDIT EVIDENCE**
> "Show me every failed sign-in for this account" and "who granted dave admin, and when?" are standard audit
> questions. Keycloak's own event store keeps them for 30 days. Step 23 copies them into the platform's
> tamper-evident audit log for long-term retention.

> **TIP · TYPING VERY FAST LOCKS SOONER**
> Keycloak also has a "quick login check": two failures less than a second apart lock the account for a minute
> straight away, because no human types that fast. Typing at human speed, you will see exactly five
> `invalid_user_credentials` errors before the lockout.

### 8 · Record the decision

```bash
just adr "Use Keycloak for identity"
```

The decision record is `docs/adr/0016-use-keycloak-for-identity.md`: Keycloak 26.8.x (digest-pinned, production
mode, own Postgres) on `127.0.0.1:8180` with issuer `http://localhost:8180/realms/rag`; the realm defined in
`realm-rag.json` with no secrets; groups mirror documents' `acl_groups` and roles attach to groups only; the five
clients and their flows; the password grant disabled everywhere; password policy, lockout, MFA for admins,
5-minute access tokens, one-time refresh tokens, login + admin events; the temporary bootstrap admin replaced by a
personal admin with MFA. Alternatives weighed: Authentik / Zitadel, Ory, Entra ID / Okta / Auth0, and rolling our
own logins. Revisit for corporate SSO, multi-tenancy (Keycloak Organizations) or HA in Kubernetes.

```bash
git add -A
git commit -m "feat(identity): Keycloak realm rag with groups, roles, clients and service accounts"
git push -u origin feat/keycloak
gh pr create --fill && gh pr merge --squash --delete-branch
git switch main && git pull
```

## Benefits

- **One identity for everything:** sign in once; every app and API trusts the same tokens.
- **Retrieval permissions from real data:** the `groups` claim feeds the document filter directly.
- **Strong sign-in out of the box:** password policy, lockout, MFA, short-lived and one-time tokens.
- **Least privilege for machines:** separate service accounts, each with the narrowest role.
- **Configuration as code:** the realm is reviewed in pull requests and reproducible.
- **Audit-ready:** login and admin events from day one.
- **Standards, not lock-in:** OIDC tokens work with any language, gateway or cloud.

## Drawbacks and risks

- **Heavier than it looks:** a Java service plus its own database, around 1–1.5 GB of RAM.
- **Configuration drift:** startup import is one-time only; you need a sync tool or discipline.
- **Many settings to get wrong:** redirect URIs, mappers, lifetimes. Small mistakes become security holes.
- **Tokens are bearer tokens:** whoever holds one can use it until it expires. Keep them short-lived and never
  log them.
- **Group changes take effect at the next token:** up to 5 minutes' delay (shorter lifetimes, or revocation, if
  that matters).
- **Large groups bloat tokens:** someone in 300 groups gets a huge token. Use plain names and filter which groups
  are mapped.
- **Single instance here:** no high availability until Kubernetes (Step 29).

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| **Keycloak** (our choice) | Full open-source identity server (CNCF) | Self-hosted, enterprise features, federation and brokering |
| **Authentik** | Open-source IdP with a friendly UI and flows | Smaller teams who want easier admin |
| **Zitadel** | Open-source, multi-tenant-first IdP | SaaS products with many customer organisations |
| **Ory (Kratos, Hydra, Keto)** | Headless identity building blocks | You want full control of the login UI and are happy to assemble pieces |
| **Authelia / oauth2-proxy** | Lightweight sign-in in front of apps | Protecting internal tools, not a full IdP |
| **Dex** | Federation-only OIDC bridge | You only need to connect to an existing directory |
| **Managed (Entra ID, Okta/Auth0, Cognito, Google Identity)** | Hosted identity | The company already uses it; broker to it from Keycloak, or use it directly in cloud (Step 37) |

The ADR adds one more option the guide rules out entirely: **rolling our own logins** (full control, but a security
risk and months of work: never for production).

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Local, self-contained enterprise platform | Keycloak realm as code (this step) |
| Company already has Entra ID / Okta | Keycloak brokers to it, or apps trust it directly |
| On-premises Active Directory | Keycloak LDAP user federation |
| Many customer organisations (B2B SaaS) | Keycloak Organizations or Zitadel; tenant id in the token (Step 36) |
| Accounts must follow HR systems automatically | SCIM provisioning from the directory |
| Machine-to-machine calls | Client credentials per service, or workload identity in Kubernetes |
| Web app sign-in | Authorization code + PKCE; never implicit flow or password grant |

## Common mistakes

- Using the `master` realm for applications, or keeping the temporary admin forever.
- Enabling the password grant ("Direct access grants") to make scripts easy.
- Wildcard redirect URIs like `*`: an attacker can have tokens sent to their own site.
- Giving roles to individual users instead of groups, so access reviews become impossible.
- Long-lived access tokens (hours or days) to avoid refresh logic.
- Trusting a decoded token without checking the signature, issuer and audience (Step 17).
- Logging tokens in application logs; they're credentials.
- Editing the realm file and expecting a restart to apply it (import runs once).
- A different issuer inside and outside containers, so APIs reject valid tokens (fixed by `KC_HOSTNAME`).
- Not backing up Keycloak's database: losing it means losing every account and setting.

## Done when

- [ ] `KEYCLOAK_DB_PASSWORD`, `KEYCLOAK_PROVISIONER_SECRET`, `KEYCLOAK_INGESTION_SECRET` are encrypted;
      `.env.example` and the generator are updated
- [ ] `keycloak` (26.8.x, pinned) and `keycloak-db` are healthy; port 9000 is not published
- [ ] The discovery document shows issuer `http://localhost:8180/realms/rag`
- [ ] `temp-admin` is deleted; your personal admin signs in with MFA
- [ ] `just kc-users` creates five users, re-runs without changes, and shows 403 for listing clients
- [ ] `just kc-whoami` shows alice's groups and `rag-user` role, the machine's `rag-ingest` role with no refresh
      token, and a failed refresh after logout
- [ ] Five wrong passwords lock bob temporarily; events show the failures and admin changes
- [ ] ADR-0016 is merged through a PR

## Recap

> **RECAP**
> The platform now has a badge office. Keycloak signs people in with strong rules (password policy, lockout,
> MFA) and machines in with client credentials. It hands out short-lived signed tokens carrying groups (what you
> can see) and roles (what you can do), all defined as code in one realm file and logged as events. Nothing
> checks those tokens yet. Step 17 puts that guard on the doors: the APIs will verify each token's signature,
> issuer, audience and expiry before answering.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `infra/config/keycloak/realm-rag.json` | The realm `rag` as code: sign-in rules, password policy, temporary lockout, token lifetimes, login/admin events, four realm roles, six groups with roles attached, `all-staff` as default group, the five clients (`rag-api`, `rag-web`, `rag-cli`, `ingestion-worker`, `rag-provisioner`) with audience and `groups` mappers, and the two least-privilege service accounts. Secrets only as `${…}` placeholders. |
| `infra/compose/compose.yaml` (changed) | New `keycloak-db` (Postgres 17, same pinned image as `litellm-db`, no published port) and `keycloak` (26.8.0 pinned by tag@digest, production mode, `--import-realm`, passwords and client secrets from four secret files, fixed issuer, only `127.0.0.1:8180` published, readiness healthcheck on internal port 9000) services, the `keycloak-db-data` volume and four `keycloak_*` secrets. |
| `scripts/new-dev-secrets.sh` (changed) | Also generates `KEYCLOAK_DB_PASSWORD`, `KEYCLOAK_PROVISIONER_SECRET` and `KEYCLOAK_INGESTION_SECRET`. |
| `.env.example` (changed) | Lists the three new Keycloak names (no values) and what each is for. |
| `justfile` (changed) | `just kc-users` and `just kc-whoami`, both run with the SOPS secrets in memory. |
| `scripts/kc_users.py` | Creates the five demo users (one-time passwords, MFA required for dave and erin) in their groups through the `rag-provisioner` service account; idempotent; proves the account can't list clients (403). |
| `scripts/kc_whoami.py` | Device-flow sign-in as a person, client-credentials sign-in as the ingestion worker, decodes both access tokens for viewing, then logs out and shows the refresh token is dead. |
| `tests/test_keycloak.py` | Static checks of both services, the secrets wiring, every realm rule, the clients and mappers, the service accounts, the generator, recipes, scripts and ADR; live checks (opt-in) of the issuer, the unpublished port 9000, the refused password grant, the machine token and the provisioner's limits. |
| `pyproject.toml`, `uv.lock` (changed) | `httpx` added to the dev group so strict mypy and the tests can check the two scripts. |
| `docs/adr/0016-use-keycloak-for-identity.md` | ADR-0016, plus its row in `docs/adr/README.md`. |
| `docs/steps/step-16-keycloak-realm-users-groups.md` | This write-up, plus its row in `docs/steps/README.md`, the changelog entry and new glossary terms. |

## Notes for this repository

- **The image digest is real, and was checked through Docker Hub.** The guide leaves `<digest>`. `quay.io` was not
  reachable from the build container, but the Keycloak project publishes the same images to Docker Hub
  (`keycloak/keycloak`); the multi-arch index digest of `26.8.0` there is
  `sha256:27b3230fbabb8c9ff3c66c864cf09dcd8a41aca82e5100679d109ef0eeb05741`, and the Compose file pins
  `quay.io/keycloak/keycloak:26.8.0@sha256:27b3…` as the guide writes it. Run the guide's
  `docker buildx imagetools inspect quay.io/keycloak/keycloak:26.8.0` on your Mac to confirm before `just up`.
  `keycloak-db` reuses the `postgres:17-alpine` digest already pinned for `litellm-db` in Step 10.
- **The scripts wrap their steps in `main()`.** The guide's two scripts run at module level. Here the same code
  sits in a `main()` function called under `if __name__ == "__main__":`, so the tests can import `USERS` and
  `claims()` without signing in to anything. Behaviour and output are unchanged; a few type annotations
  (`dict[str, Any]`) satisfy strict mypy, the indentation of `show()`'s output is two spaces, and ruff formatted the
  code.
- **`httpx` is a dev dependency.** The recipes still run the scripts with `uv run --with httpx`, exactly as the
  guide says; the dev group also gets `httpx>=0.28.1` so mypy and `tests/test_keycloak.py` can use it.
- **Back-channel addresses follow the caller.** Because of `KC_HOSTNAME_BACKCHANNEL_DYNAMIC`, the discovery
  document fetched through `http://127.0.0.1:8180` lists `jwks_uri` and `token_endpoint` under `127.0.0.1`, and
  through `localhost` (as in the guide's `curl`) under `localhost`. The `issuer` is always
  `http://localhost:8180/realms/rag`. That is the point of the setting, and Step 17 relies on it.
- **A `gitleaks:allow` marker on the database URL.** gitleaks (Step 5) mistakes
  the `KC_DB_URL` value (a JDBC URL) for a credential because of its shape. It holds no password (that is
  `KC_DB_PASSWORD`, from a secret file), so the Compose line and the matching test line carry an inline
  `# gitleaks:allow` comment instead of weakening the scanner for the whole repository.
- **No real secrets are committed.** Only the names appear, in `.env.example`; the generator creates real values
  per machine, encrypted by SOPS. Your existing `secrets/dev.enc.env` is updated with `just secrets-edit` as in
  section 1. Steps 4 (personal admin with MFA) and the browser parts of 6 and 7 are done by hand in the console.
- **Faithful formatting fixes.** PDF line wraps inside the realm JSON (the password policy string, the mapper
  names), the Compose `secrets:` list and healthcheck, the ADR table and the Python were rejoined, and indentation
  reconstructed.
- **What was validated here (Linux container with Docker, no Mac, no SOPS key).** The real Keycloak 26.8.0 image
  (same digest, pulled through a Docker Hub mirror) and `postgres:17-alpine` were started with this Compose file
  and random test secrets. `keycloak-db` and `keycloak` became **healthy** with the guide's bash healthcheck; the
  log showed `Realm 'rag' imported`, and after a restart `Realm 'rag' already exists. Import skipped`; the discovery
  document showed issuer `http://localhost:8180/realms/rag`; port 9000 was not published. `kc_users.py` created the
  five users, printed `provisioner -> list clients: 403 (403 expected)`, and a second run printed `already exists`
  for each. `kc_whoami.py` was run with the device page approved by a small helper (sign-in as alice, then
  "Yes"): the output above is from that run, including `machine got a refresh token? False` and
  `refresh after logout -> 400 invalid_grant`. The password grant was refused for `rag-cli`
  (`unauthorized_client`), the password policy refused reusing an old password, and five wrong passwords for bob
  (at human speed) produced five `LOGIN_ERROR invalid_user_credentials` events, a `USER_DISABLED_BY_TEMPORARY_LOCKOUT`
  event and a refusal of his correct password with the same neutral message; admin events listed the provisioner's
  `CREATE USER` and `CREATE GROUP_MEMBERSHIP` changes. `tests/test_keycloak.py` passed in full against the running
  server (25 tests), and the static part passes without it. The test stack, its volume and the image were removed
  afterwards.
