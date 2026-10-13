# ADR-0029: Run rag-api on Kubernetes, deployed by Argo CD from git

- **Status:** Accepted
- **Date:** 2026-10-13
- **Deciders:** deivamanikailasam

## Context
Compose runs the platform on one Mac but gives no safe rollouts, no enforcement of what may run,
and no record of what is deployed. Releases are signed (Step 27) but nothing required that only
signed, pinned images run.

## Decision
OrbStack's single-node Kubernetes runs rag-api (stateless); stateful services stay in Compose,
reached through ExternalName services. Manifests use Kustomize (base, external-deps component,
per-environment overlay). Namespace rag enforces Pod Security "restricted" plus two
ValidatingAdmissionPolicies (digest-pinned images from our registry; requests, memory limit,
read-only root, no automounted API token), a ResourceQuota and a LimitRange. rag-api runs 2
replicas with maxUnavailable 0, a PDB and NetworkPolicies; an OpenBao Agent native sidecar logs in
with a projected service account token (audience openbao, 10 min) verified offline by OpenBao's
JWT method. Argo CD 3.5 (vendored release manifest, SHA-256 recorded) syncs from main with an app
of apps, two projects (platform, rag), sync waves, self-heal and server-side apply. Promotion is a
verified, one-line digest change by pull request; rollback is git revert. Manifests are tested
against a real kube-apiserver in CI and scanned by Trivy with dated, explained exceptions.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Helm chart for rag-api | Standard packaging, values | Templates hide the real YAML; one more tool | Kustomize is built into kubectl; Argo CD supports both |
| Flux | CNCF graduated, lightweight | No built-in UI | Argo CD's UI helps while learning |
| Push-based deploys from CI (kubectl apply) | Simple | CI needs cluster credentials; no drift correction | GitOps pull model |
| Kyverno / Gatekeeper / Sigstore policy-controller | Richer policies, in-cluster signature checks | Extra controllers to run and secure | Built-in VAP first; signature check at promotion |
| Kubernetes auth method in OpenBao | Revocation via TokenReview | OpenBao must reach and authenticate to the API | JWT method works offline |
| kind / k3d / minikube | Multi-node, scriptable | Another VM/runtime | OrbStack already runs it |

## Consequences
+ Only reviewed, verified, digest-pinned images run; drift is corrected; rollback is a revert.
+ No application secret is a Kubernetes Secret; pod restarts need no human.
- Two runtimes (Compose and Kubernetes) to understand while stateful services stay in Compose.
- NetworkPolicy and pod→Compose connectivity depend on OrbStack (checked by recipes).
- Signature verification happens at promotion, not again in the cluster.

## Revisit when
A second environment or node, a managed cluster, moving Postgres in (CloudNativePG), or more
than one team deploying (add in-cluster signature verification and SSO for Argo CD).
