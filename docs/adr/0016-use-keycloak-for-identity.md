# ADR-0016: Use Keycloak for identity

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** deivamanikailasam

## Context
Permission-aware RAG needs each request tied to a real person or machine, with group membership
for document filtering and roles for actions. Shared API keys can't tell users apart.

## Decision
Run Keycloak 26.8.x (digest-pinned, production mode, own Postgres) on 127.0.0.1:8180 with issuer
http://localhost:8180/realms/rag. Realm "rag" is defined in infra/config/keycloak/realm-rag.json
(no secrets; ${} placeholders). Groups mirror documents' acl_groups; roles attach to groups only.
Clients: rag-web (auth code + PKCE), rag-cli (device flow), rag-api (audience), ingestion-worker and
rag-provisioner (client credentials, least-privilege service accounts). Password grant disabled
everywhere. Password policy, brute-force lockout, MFA for admins, 5-minute access tokens, one-time
refresh tokens, login + admin events. Temporary bootstrap admin replaced by a personal admin with MFA.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Authentik / Zitadel | Modern UIs, good OIDC | Smaller enterprise footprint | Keycloak is the de-facto standard and CNCF project |
| Ory (Kratos + Hydra) | Cloud-native building blocks | Several components to assemble | More integration work |
| Entra ID / Okta / Auth0 | Managed, corporate directory | Cloud dependency, cost, not local | Broker to them later instead |
| Roll our own logins | Full control | Security risk, months of work | Never for production |

## Consequences
+ One sign-in for every app; tokens carry groups and roles for Steps 17-18.
+ Standards-based (OIDC/OAuth 2.0): any framework or gateway can verify the tokens.
- Another stateful service (~1 GB RAM) whose database must be backed up.
- Realm import runs only once; ongoing changes need a sync tool (keycloak-config-cli or Terraform).

## Revisit when
Corporate SSO (federation/brokering), multi-tenancy (Keycloak Organizations), or HA in Kubernetes.
