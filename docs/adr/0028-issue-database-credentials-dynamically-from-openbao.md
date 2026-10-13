# ADR-0028: Issue database credentials dynamically from OpenBao

- **Status:** Accepted
- **Date:** 2026-10-13
- **Deciders:** deivamanikailasam

## Context
Services used long-lived, shared database passwords from SOPS files. A leaked password stayed
valid until rotated by hand in several places; all instances logged in as the same role; nobody
could tell who had used a secret, when.

## Decision
Run OpenBao 2.7 (MPL-2.0 fork of Vault): one node, raft storage, Shamir 3/2 unseal with the shares
and root token in a SOPS file, file audit device declared in server.hcl, Prometheus metrics.
Database secrets engine with one admin login per database (CREATEROLE, ADMIN OPTION on the
group roles only), root passwords rotated immediately. Dynamic users are members of the
existing group roles, VALID UNTIL their lease, TTL 1 h, max 24 h. rag-api gets credentials through
an OpenBao Agent sidecar (AppRole, response-wrapped single-use secret ID, CIDR-bound) that writes
files to a tmpfs shared only with rag-api, which reads them per connection. KV v2 holds the
gateway key and OPA token. Policies per client; admin via userpass without read access to secret
values; root token revoked after setup; generate-root is the break-glass path. All configuration
is in git and applied by scripts/vault_setup.py. Static passwords remain for rollback until the
cut-over is confirmed.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| HashiCorp Vault | Reference product, Enterprise features | BUSL-1.1 licence, now IBM | Licence policy; OpenBao is API-compatible |
| Keep SOPS only, rotate by hand | Nothing new to run | Long-lived shared passwords, no usage audit | The problem we're solving |
| Infisical / Doppler / 1Password Secrets Automation | Friendly UI, SaaS | Mostly static secrets; SaaS dependency | No dynamic database users on our terms |
| Cloud secret managers (AWS, Azure, GCP) | Managed, IAM-integrated | We run locally, no cloud | Revisit when deployed to a cloud |
| Kubernetes Secrets + External Secrets Operator | Native in Step 29 | Still static values; needs a backend anyway | Complements OpenBao later |
| Postgres IAM/OIDC authentication | No passwords at all | Not available for self-hosted Postgres 17 | Revisit with managed Postgres |

## Consequences
+ Database logins are per-client, expire within an hour, are revocable instantly and audited.
+ No person knows the database admin passwords; the root token isn't used day to day.
- OpenBao is a new critical service: sealed or down means no new credentials (existing ones
  last up to an hour). Unsealing after every restart is a manual step.
- The agent needs a fresh secret ID after every restart.

## Revisit when
Moving to Kubernetes (Step 29: Kubernetes auth instead of AppRole, auto-unseal with a KMS),
running more than one node, or adopting managed Postgres with IAM authentication.
