# ADR-0017: Validate JWTs locally in every service

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** deivamanikailasam

## Context
Services must know who is calling, with groups for document filtering and roles for actions.
Keycloak (ADR-0016) issues RS256-signed JWT access tokens with a 5-minute lifetime.

## Decision
Every service validates tokens itself with rag_common.auth.TokenVerifier (PyJWT): RS256 only;
keys from Keycloak's JWKS (cached 5 min, re-fetched on unknown kid); issuer, audience "rag-api",
exp/iat/sub required, 30 s leeway; typ must be "Bearer"; azp must be an allowed client. Invalid
token -> 401 with WWW-Authenticate; key service unreachable -> 503; missing role -> 403. Groups
are taken only from the verified token; empty groups match no documents. Gateway calls carry
user=sub. Tokens are never logged. Negative tests cover each attack; they run on every push.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Introspection (RFC 7662) per request | Instant revocation | Network call per request; Keycloak becomes a hard dependency | Short tokens make local validation enough |
| Validate only at an API gateway (Kong, Envoy, oauth2-proxy) | One place to configure | Services trust the network; groups still needed inside | Add later as defence in depth, not instead |
| python-jose / Authlib | Also mature | jose is barely maintained; Authlib is broader than needed | PyJWT is focused and actively maintained |
| Keycloak-specific client libraries | Less code | Ties services to one vendor | Standard OIDC keeps us portable |

## Consequences
+ Fast, standards-based checks; services keep working through a Keycloak restart.
+ One shared, tested verifier for every service.
- Revocation is delayed by up to one token lifetime (5 minutes).
- Bearer tokens can be replayed if stolen (sender-constrained tokens, DPoP/mTLS, are the upgrade).

## Revisit when
Instant revocation is required, tokens must be sender-constrained, or a service mesh/gateway takes
over edge auth.
