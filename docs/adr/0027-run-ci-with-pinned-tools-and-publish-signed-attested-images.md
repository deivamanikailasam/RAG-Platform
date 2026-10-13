# ADR-0027: Run CI with pinned tools and publish signed, attested images

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** deivamanikailasam

## Context
Checks ran only when someone remembered; Step 26 broke the image build unnoticed. The build pulls
third-party actions, tools, Python packages and base images, any of which can be compromised, and
we could not prove what an image contained or where it came from.

## Decision
GitHub Actions. ci.yml (PRs, main, merge queue): checks (just ci-static, ci-test with a Postgres
service, ci-config, policy-check), supply-chain (gitleaks on full history, actionlint, zizmor,
pip-audit on uv.lock, licence policy, Trivy on the Dockerfile), image (Buildx build without push,
Trivy image scan failing on fixable HIGH/CRITICAL, Syft CycloneDX SBOM). release.yml (main):
build once, push by digest to ghcr.io, cosign keyless signature, SLSA build provenance and SBOM
attestations. evals.yml: self-hosted Mac runner, same-repo PRs only, approval environment.
All actions pinned by commit SHA with version comments; tool binaries pinned by SHA-256 in
ci/tools.yaml; read-only default permissions; no pull_request_target; Dependabot weekly for
actions, uv and Docker. Repository rules require these checks, a CODEOWNERS review, signed commits
and linear history. Pipeline rules are enforced by tests.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| GitLab CI / Jenkins / Buildkite | Mature, self-hostable | Repository already on GitHub; more to run | Revisit if the code moves |
| Long-lived signing key (cosign key pair) | Works offline | Key storage, rotation, leaks | Keyless needs no secret |
| Docker Content Trust (Notary v1) | Built into Docker | Effectively superseded by Sigstore and Notary v2 | Ecosystem moved on |
| Snyk / GitHub Advanced Security | Rich UI, databases | Cost; vendor lock-in | Open tools first; add if needed |
| Renovate instead of Dependabot | Can update ci/tools.yaml, richer rules | Another app to configure | Dependabot covers 3 of 4 pin types |

## Consequences
+ Every change is tested identically to local runs; broken builds and known-bad dependencies are
  blocked.
+ Images are traceable (SBOM, provenance) and verifiable (signature on digest).
- Pins need regular updates (Dependabot PRs; monthly tools.yaml review).
- Self-hosted runner on a personal Mac needs care (fork guard, approvals, runner as your user).

## Revisit when
The repository becomes public (remove the self-hosted runner), images are deployed (Step 29:
verify in the cluster), or the team grows (merge queue, reusable workflows for SLSA level 3).
