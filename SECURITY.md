# Security policy

> **IN PLAIN ENGLISH**
> If you find a security problem, tell the maintainer privately, not in a public issue, so it can be
> fixed before anyone can misuse it. If a password, key or token has leaked, rotate it first and ask
> questions later: the runbook below says exactly how.

## Reporting a vulnerability

- **Do not** open a public issue, discussion or pull request describing the problem.
- Report it privately to the repository owner (**@deivamanikailasam**) through GitHub's private
  vulnerability reporting on this repository (*Security → Report a vulnerability*). If that option
  isn't available, contact the owner through GitHub and ask for a private channel before sending details.
- Include: what is affected (file, service, endpoint, version or commit), how to reproduce it, what an
  attacker could do, and any suggested fix. Don't include real personal data or live secrets.
- You'll get an acknowledgement, an assessment, and a fix or mitigation plan; a public advisory follows
  once a fix is available. Please give a reasonable time to fix before disclosing.

Out of scope: findings that need an already-compromised workstation, the deliberately insecure local
development defaults that are documented (for example OpenSearch's self-signed certificate in dev, or
services bound to `127.0.0.1` without TLS), and placeholder values that the docs say to replace.

## If a secret has leaked

Follow [docs/runbooks/secret-leak.md](docs/runbooks/secret-leak.md) **now**: revoke or rotate at the
source first, update it (`just secrets-edit`, or `just vault-put …` for values in OpenBao), restart what
uses it, then assess, clean up history only after rotating, and record what happened. For OpenBao
credentials and break-glass procedures see [docs/runbooks/openbao.md](docs/runbooks/openbao.md).

## Supported versions

| Component | Supported |
|---|---|
| `main` branch (the platform as deployed through `deploy/envs/*`) | Yes: fixes land here and are promoted through the gates |
| `rag-core` 1.x ([changelog](libs/rag-core/CHANGELOG.md)) | Latest 1.x release; projects pin `rag-core>=1.x,<2` and take fixes with `uv lock --upgrade-package rag-core` |
| Older images | No: roll forward by promoting a fixed digest (`just promote … "INC-…: reason"` for an urgent fix) |
| Third-party components (Keycloak, OpenBao, Postgres, …) | Pinned by digest; upgraded through Dependabot or the `just vendor` / `just argocd-vendor` recipes in a reviewed PR |

## How the platform protects itself

A summary of the controls (each with test evidence) is in
[docs/guides/quality-and-operations.md](docs/guides/quality-and-operations.md#3-security-and-safety);
the full threat model is [docs/security/threat-model.md](docs/security/threat-model.md) and the controls
matrix is [docs/compliance/controls.md](docs/compliance/controls.md).

> **NOTE · SELF-HOSTED RUNNER**
> `.github/workflows/evals.yml` targets a self-hosted runner on the owner's Mac. Self-hosted runners must
> not be attached to a public repository; see the
> [pre-production checklist](docs/guides/production-promotion.md#11-pre-production-checklist).
