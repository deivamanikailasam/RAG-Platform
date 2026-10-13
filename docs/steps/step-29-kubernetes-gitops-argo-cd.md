# Step 29 · Kubernetes and GitOps with Argo CD

*Step 29 of 38 · Phase G · Quality & delivery*

## At a glance

| | |
|---|---|
| **Goal** | rag-api runs on Kubernetes, and the only way anything changes there is a merged pull request. Argo CD watches git and makes the cluster match it, continuously; the cluster refuses anything that breaks the platform's rules. |
| **How, in one sentence** | OrbStack's built-in single-node cluster runs rag-api (2 replicas, each with an OpenBao Agent native sidecar that logs in with the pod's own Kubernetes identity); Kustomize describes it; the API server's own Pod Security and ValidatingAdmissionPolicies refuse unpinned images, root containers and missing limits; Argo CD syncs from `main`, and `just promote` turns a verified, signed image digest into a one-line pull request. |
| **Time** | About 3 to 4 hours. |
| **You'll end up with** | `deploy/`: guard rails (`cluster/`), rag-api (`base/`, `envs/local/`), the link to Compose (`components/external-deps/`), and Argo CD (`argocd/`: install, projects, applications) · rag-api pods that are non-root, read-only, digest-pinned, resource-limited, behind NetworkPolicies, with no Kubernetes API token and no secret to hand over · OpenBao trusting the cluster's service account tokens, checked offline with the cluster's public key · Argo CD managing itself, the guard rails and rag-api ("app of apps"), with self-heal and least-privilege projects · promotion and rollback as git commits; a Kubernetes misconfiguration scan in CI · 43 new tests (263 in total in the guide's count), most of them against a real Kubernetes API server · ADR-0029, a runbook, and the end of the platform half of the guide. |
| **New words** | container orchestration, cluster, node, control plane, API server, etcd, kubelet, controller, reconciliation, desired state, Pod, Deployment, ReplicaSet, Service, namespace, ServiceAccount, ConfigMap, manifest, label/selector, probe, rolling update, PodDisruptionBudget, ResourceQuota, LimitRange, NetworkPolicy, admission control, Pod Security Standards, ValidatingAdmissionPolicy, CEL, native sidecar, projected service account token, Kustomize (base, overlay, component), Helm (chart, values, release), GitOps, Argo CD (Application, AppProject, sync, self-heal, prune, sync wave, app of apps), promotion. |

## The big idea

> **ANALOGY · THE THERMOSTAT**
> You don't heat a room by switching the heater on and off yourself. You set the thermostat to 21 °C and walk
> away. It measures, compares, and switches the heater on or off as often as needed. Open a window and it
> simply works harder until the room is back at 21 °C.
>
> That is how Kubernetes and Argo CD work:
> - You never say "start a container". You write down what you want ("two copies of rag-api, this version,
>   these limits"): the setting on the thermostat. That's the **desired state**.
> - Kubernetes keeps the running containers matching what it was told, restarting and replacing them as
>   needed.
> - Argo CD keeps what Kubernetes was told matching git. Someone changes something by hand in the
>   cluster? It's set back, like the open window.
>
> So the thermostat's dial is a file in git, and turning it is a reviewed pull request.

### GitOps in this platform (Figure 92)

The whole flow, from a release to running pods:

1. **release** — `main` builds, signs and publishes `rag-api@sha256:…` (Step 27).
2. **`just promote`** — verifies the signature and provenance, changes ONE line, opens a pull request.
3. **review + CI** — the diff *is* the change: old digest → new digest. Merge = deploy.
4. Argo CD (inside the cluster) **pulls `main`** every 3 minutes (or on a webhook).
5. It **compares** git with the cluster: the diff.
6. It **applies the difference** (a sync), in waves: `deploy/cluster` (guard rails), `deploy/envs/local` (rag-api), `deploy/argocd` (Argo CD itself).
7. In the cluster (OrbStack), new pods start; the old ones stay until the new are ready.
8. **Admission** checks every object (Pod Security, our policies).
9. Hand-made changes are reverted: **self-heal**.

Rolling back is `git revert` of the promotion commit. Nobody runs `kubectl apply` against the cluster by hand.

## What we're doing

1. Start OrbStack's Kubernetes and learn the handful of objects we need.
2. Put the guard rails in first: a restricted namespace, quotas, and two admission policies.
3. Describe rag-api with Kustomize: a base, a component that links to Compose, and a local overlay.
4. Give pods a secret-free login to OpenBao: the pod's own service account token.
5. Test all of it against a real Kubernetes API server.
6. Install Argo CD (vendored and hash-checked), with two projects and an app of apps.
7. Promote releases and roll back with one-line commits; scan the manifests in CI.
8. Write the runbook and ADR-0029, and look back at the whole platform.

## Why we're doing this

> **WHY THIS MATTERS**
> Compose (Steps 9 to 28) runs containers well on one machine. What it doesn't give you:
> - **Self-healing and safe rollouts.** If a container dies, Compose can restart it, but it can't roll out a new version
>   gradually, keep serving during the change, or refuse to remove the last working copy.
> - **Rules the platform enforces itself.** In Compose, nothing stops someone from running `:latest` as root.
>   Kubernetes checks every object before it exists.
> - **A record of what runs.** "What's deployed, and since when?" is answered by `docker ps` and memory. With
>   GitOps it's answered by `git log deploy/`.
> - **The way most companies run services.** Kubernetes is the common runtime across clouds and data
>   centres; what you learn here transfers.
>
> The stateful services (databases, Keycloak, OpenBao, the model gateway) stay in Compose for now: on one
> Mac they're simpler and safer there, and moving stateful systems is its own project. rag-api, stateless, is the
> right first workload.

| Need | How this step meets it |
|---|---|
| Deploy without downtime, roll back fast | Deployment with `maxUnavailable: 0`, PodDisruptionBudget, readiness probes; rollback = `git revert` |
| Only reviewed changes reach the cluster | Argo CD syncs only from `main`; self-heal reverts hand-made changes |
| Only verified images run | `just promote` verifies signature + provenance; the cluster admits only digest-pinned images from your registry |
| Containers can't do more than they need | Pod Security `restricted`, read-only root filesystem, all capabilities dropped, no API token, NetworkPolicies |
| No secrets in Kubernetes for the app | OpenBao Agent sidecar logs in with the pod's service account token; only 2 bootstrap Secrets exist |
| A noisy app can't starve the Mac's models | ResourceQuota and LimitRange on the namespace, limits on every container |
| Know the manifests are right before deploying | 43 tests, mostly against a real API server; Trivy misconfiguration scan in CI |

> **IN A COMPANY**
> - GitOps is described by the CNCF's **OpenGitOps principles** (v1.0): the desired state is declarative,
>   versioned and immutable (git), pulled automatically, and continuously reconciled. Argo CD and Flux are
>   the two CNCF-graduated GitOps tools.
> - Kubernetes hardening guidance: the **Pod Security Standards** (built in), the **NSA/CISA Kubernetes
>   Hardening Guide**, and the **CIS Kubernetes Benchmark**. Auditors ask: who can change production, how is it
>   reviewed, can you show what ran when?
> - **Separation of duties:** in this step, Argo CD projects separate the platform team's guard rails from the
>   application team's deployments. The application can't loosen its own limits.
>
> Real clusters have several nodes across failure zones, managed control planes (EKS, GKE, AKS), and in-cluster
> image signature verification. The objects and the GitOps flow are the same as here.

## Key ideas

| Term | Plain-English meaning |
|---|---|
| Cluster, node | A group of machines (nodes) Kubernetes runs containers on. OrbStack gives you a cluster of one node. |
| API server, etcd | The cluster's front desk (every change goes through it) and its database. |
| Controller, reconciliation | A loop that compares desired state with actual state and fixes the difference, forever. Kubernetes is made of them; Argo CD is one too. |
| kubelet | The agent on each node that actually starts containers, runs probes and writes service account tokens. |
| Pod | One or more containers that run together and share network and volumes. The unit Kubernetes schedules. |
| Deployment → ReplicaSet → Pods | "Keep N copies of this pod template running; change versions gradually." |
| Service | A stable name and address for a set of pods (found by labels and a selector). |
| Namespace | A folder for objects, with its own rules and limits. |
| ServiceAccount | A pod's identity inside the cluster. |
| ConfigMap / Secret | Configuration / sensitive values as objects. We use ConfigMaps; app secrets come from OpenBao. |
| Manifest | A YAML file describing an object. |
| Probes | Startup, readiness ("send me traffic?") and liveness ("restart me?") checks. |
| PodDisruptionBudget | "Never voluntarily take away more than this many pods" (e.g. during node maintenance). |
| ResourceQuota, LimitRange | A ceiling for the whole namespace; defaults and maximums per container. |
| NetworkPolicy | A firewall rule between pods, enforced by the network plugin (if it supports them). |
| Admission control | Checks the API server runs on every object before storing it. |
| Pod Security Standards | Built-in profiles (privileged, baseline, restricted) enforced per namespace by a label. |
| ValidatingAdmissionPolicy, CEL | Your own admission rules, written in a small expression language (CEL), run inside the API server. |
| Native sidecar | A helper container (an init container with `restartPolicy: Always`) that starts first and runs beside the app. Kubernetes 1.33+. |
| Projected service account token | A short-lived token the kubelet writes into the pod, for one audience only, refreshed automatically. |
| Kustomize: base, overlay, component | Plain YAML plus small, declared changes per environment. Built into `kubectl`. |
| Helm: chart, values, release | A package format with templates; values fill them in; an installed instance is a release. |
| GitOps, Argo CD | Git holds the desired state; Argo CD applies it and keeps it applied. |
| Application, AppProject | Argo CD's "this folder of git goes to that namespace", and the permission boundary around it. |
| Sync, prune, self-heal, sync wave | Apply git; delete what git no longer has; undo manual changes; order the syncs. |
| App of apps | One Argo CD Application whose folder contains the other Applications. |
| Promotion | Moving a tested, signed build to an environment; here, by changing its digest in git. |

### What runs where (Figure 93)

On your Mac (OrbStack) there are now two worlds side by side:

- **Kubernetes (one node)**
  - namespace **argocd**: Argo CD's server, repo server and application controller (Pod Security *baseline*).
  - namespace **rag** (Pod Security *restricted* plus our policies): two pods, `rag-api-abc` and `rag-api-xyz`.
    Each pod is an **openbao-agent** native sidecar that writes files, and **rag-api** (read-only, non-root)
    that reads them. Around them: a Service, a PDB (min 1), NetworkPolicies, a quota, and ExternalName
    services pointing at your Mac.
  - guard rails for the whole namespace: Pod Security restricted, images by digest from `ghcr.io/owner/`,
    limits, read-only filesystems.
- **Docker Compose (Steps 9–28)**: rag-db (Postgres: rag, audit), Keycloak, LiteLLM → models on the Mac, OPA,
  OpenBao, OTel Collector → Prometheus, Tempo, Loki, Grafana; Qdrant · OpenSearch · Valkey · object store ·
  Langfuse.

The stateful services stay in Docker Compose, reached through ExternalName services.

### How the cluster says no (Figure 94)

Every object, whether it comes from `kubectl` or Argo CD, passes these stages in the API server before it exists:

1. **Authentication** — "who are you?" (certificate, token)
2. **Authorization** — "may you?" (RBAC)
3. **Mutating admission** — fill in defaults (LimitRange, service account)
4. **Schema validation** — "well-formed?" (every field, CRDs)
5. **Validating admission** — "allowed?" (Pod Security, our ValidatingAdmissionPolicies)
6. **Stored** in etcd, then scheduled and run.

Refused at the door (real messages from this step's tests):

- `rag-api:latest` → *images must … be pinned by @sha256 digest*
- `ghcr.io/someone-else/…` → *images must come from ghcr.io/owner/ …*
- `runAsUser: 0` → *violates PodSecurity "restricted": runAsNonRoot != true*
- API token auto-mounted → *set automountServiceAccountToken false*
- Deployment without limits → *every container needs resource requests and a memory limit*

### How a pod logs in without a secret (Figure 95)

| Step 28 (Compose): AppRole | Step 29 (Kubernetes): the pod's own identity |
|---|---|
| you hand the agent a wrapped secret ID | the kubelet writes a 10-minute token, renewed |
| it works once; a restarted agent can't log in | nothing to hand over, nothing to lose |
| → `just vault-agent-start` after every restart | → restarts and new pods just work |

The chain: the **kubelet** writes a token for `rag:rag-api`, audience `openbao`, valid 10 minutes → the
**agent** sends it to `auth/kubernetes-jwt/login` → **OpenBao** checks the signature (cluster key), the issuer,
the audience and the subject → it issues a **token** with policy `rag-api`, valid 1 hour → database logins.

OpenBao checks the token **offline** with the cluster's public key (`just vault-k8s-trust` copies it): it never
calls the Kubernetes API, and a token for anything else (wrong audience, account or namespace) is refused.

> **KUSTOMIZE, NOT A HELM CHART, FOR OUR OWN APP**
> Helm packages Kubernetes manifests as charts: templates (Go templates in YAML) filled in from a values file.
> It's how most third-party software is distributed, and a chart for rag-api would work too. We chose Kustomize
> for our own manifests because:
> - it's built into `kubectl` (`kubectl kustomize`), so there's one tool less to pin and trust;
> - the files are plain Kubernetes YAML: what you read is what's applied, and a pull request's diff shows the
>   real change, not a change to a template;
> - environments are small, declared patches (an overlay), not conditionals in templates.
>
> Helm shines when you publish software for others to install with many options. Argo CD renders both, so
> switching later is a change of folder, not of process. Argo CD itself is installed from its plain release manifest,
> the method its documentation lists first. In this guide you meet Helm in the Alternatives, not in the build.

## How to do it

All commands are run on your Mac, from the repository root (`~/dev/rag-platform`).

```bash
cd ~/dev/rag-platform
git switch -c feat/kubernetes
brew install kubectl argocd        # kubectl includes kustomize; the argocd CLI is optional (the UI works too)
just k8s-up                        # OrbStack → Settings → Kubernetes → Enable, the first time
```

Check `kubectl --context orbstack version`: the server must be **1.33 or newer** (native sidecars). For CI and
the tests, the same Kubernetes 1.36.2 binaries are pinned in `ci/tools.yaml` (`kubectl`, `kube-apiserver`,
`etcd`, from the kubernetes-sigs "envtest" bundle).

### 1 · Guard rails first

Before anything runs, decide what may run. Everything in `deploy/cluster/` is applied by Argo CD in an early
sync wave, before any application.

- **`deploy/cluster/kustomization.yaml`** lists the four files below.
- **`deploy/cluster/namespace-rag.yaml`** creates namespace `rag` with the Pod Security labels
  (`enforce`, `warn` and `audit` all `restricted`, `enforce-version: v1.36`) and our own label
  `rag-platform/policy: enforced`, which switches our admission policies on for it.
- **`deploy/cluster/quota.yaml`** — a ResourceQuota (`requests.cpu: 4`, `requests.memory: 4Gi`,
  `limits.memory: 6Gi`, `pods: 20`) because the Mac's models need most of the memory (Step 7), and a
  LimitRange: default request `50m` / `64Mi`, default memory limit `256Mi`, max `2Gi` per container.
- **`deploy/cluster/policy-images.yaml`** — ValidatingAdmissionPolicy `rag-images-pinned`: for Pods,
  Deployments, StatefulSets, DaemonSets, ReplicaSets, Jobs and CronJobs, every container image (including
  init and ephemeral containers) must match
  `^(ghcr\.io/owner/|quay\.io/openbao/)[a-z0-9._/-]+@sha256:[a-f0-9]{64}$`. Its `messageExpression` names
  the offending images. Replace `owner` with your GitHub owner, lower case (also in the message).
- **`deploy/cluster/policy-workloads.yaml`** — ValidatingAdmissionPolicy `rag-workloads-hardened`: every
  container needs resource requests and a memory limit, `readOnlyRootFilesystem: true`, and the pod must set
  `automountServiceAccountToken: false`.

Both policies have a ValidatingAdmissionPolicyBinding with `validationActions: [Deny, Audit]` and a
`namespaceSelector` on `rag-platform/policy: enforced`.

> **READING THE GUARD RAILS**
> - Pod Security `restricted` is one label, and the API server does the rest: non-root, no privilege escalation,
>   every capability dropped, seccomp on. `enforce-version: v1.36` pins the rules, so a cluster upgrade
>   can't silently change them.
> - Two of our own rules fill the gaps: images must be from `ghcr.io/owner/` (yours) or `quay.io/openbao/`,
>   by digest; and every container needs requests and a memory limit, a read-only root filesystem, and pods
>   mustn't get an automatic API token.
> - CEL (Common Expression Language) is small and safe: no loops that run forever, no network calls. The
>   `variables` find the pod spec in a Pod, a Deployment or a CronJob, so the same rule covers all of them.
> - Deployments are checked, not just Pods: a bad Deployment is refused when Argo CD applies it, instead of
>   being stored and then failing to create pods later (tested).
> - `validationActions: [Deny, Audit]`: refuse, and also record the refusal in the API server's audit log.
> - Scope: the policies apply only to namespaces labelled `rag-platform/policy: enforced` (tested: an
>   unlabelled namespace is unaffected).
> - Replace `owner` with your GitHub owner in lower case, here and in the other files that say so.

> **A BARE POD GETS DEFAULTS; A DEPLOYMENT GETS REFUSED**
> The LimitRange adds a 256 MiB memory limit to a container that has none. That happens in mutating
> admission, before our validating policy looks. So a bare Pod without limits is accepted with the default, while a
> Deployment without limits is refused, because LimitRange only fills in Pods. Both behaviours are tested; the
> Deployment check is the one that keeps the manifests honest.

### 2 · rag-api, described once

`deploy/base/rag-api/` holds the environment-independent description:

- **`kustomization.yaml`** — adds the labels `app.kubernetes.io/name: rag-api` and
  `app.kubernetes.io/part-of: rag-platform` to every object *and* every selector (`includeSelectors: true`);
  lists the five resources; generates the ConfigMap `rag-api-openbao-agent` from `openbao-agent.hcl` (a content
  hash is added to its name, so changing the agent config rolls the pods); and maps the image name `openbao`
  to `quay.io/openbao/openbao` by digest. Which `rag-api` build runs where is the overlay's job.
- **`serviceaccount.yaml`** — the pod's identity, with `automountServiceAccountToken: false`: rag-api never
  talks to the Kubernetes API.
- **`deployment.yaml`** — 2 replicas, `revisionHistoryLimit: 5`, a RollingUpdate with `maxUnavailable: 0,
  maxSurge: 1`; pod security context `runAsNonRoot`, uid/gid `10001` (the image's app user from Step 17),
  `fsGroup: 10001`, seccomp `RuntimeDefault`; `enableServiceLinks: false`.
  - the **openbao-agent** native sidecar (`initContainers` with `restartPolicy: Always`) runs
    `bao agent -config=/openbao/config/agent.hcl`; its `startupProbe` waits until `/openbao/out/rag_db.json`
    is non-empty (every 2 s, up to 60 times); requests `10m`/`32Mi`, limit `64Mi`; it mounts the agent config,
    the projected token at `/var/run/secrets/openbao`, and the shared `secrets` volume at `/openbao/out`.
  - the **rag-api** container on port 8000 (`http`) with Step 17's environment variables (issuer, JWKS URL via
    `keycloak:8180`, gateway, DB hosts, OPA, the two credentials files under `/run/bao`, OpenTelemetry),
    readiness (`/healthz`, every 5 s) and liveness (`/healthz`, every 15 s, 4 failures) probes, requests
    `250m`/`256Mi`, limit `512Mi`, the `secrets` volume read-only at `/run/bao` and a `tmp` volume at `/tmp`.
  - both containers share one security context via the YAML anchor `&locked-down`:
    `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `capabilities: { drop: [ALL] }`.
  - volumes: the agent ConfigMap; `openbao-token`, a projected `serviceAccountToken` with
    `audience: openbao`, `expirationSeconds: 600`; `secrets`, an in-memory `emptyDir` (1 MiB); `tmp` (64 MiB).

> **READING THE DEPLOYMENT**
> - Two replicas, `maxUnavailable: 0`: during a rollout, a new pod must be ready before an old one goes.
>   With the PodDisruptionBudget, maintenance never takes the last pod.
> - The native sidecar (`initContainers` with `restartPolicy: Always`) starts first; rag-api starts only when
>   the sidecar's `startupProbe` sees the database login file. No race at start-up, and the agent keeps running to
>   renew and rotate.
> - `secrets` volume: `emptyDir` with `medium: Memory` is a tmpfs: secrets never touch the node's disk, and
>   they vanish with the pod. The agent writes, rag-api reads (mounted read-only).
> - `openbao-token`: a projected service account token for audience `openbao`, valid 10 minutes, refreshed by
>   the kubelet. It's mounted only into the agent, and it's useless against the Kubernetes API (wrong audience).
> - `automountServiceAccountToken: false`: the usual API token isn't mounted at all. rag-api never talks to
>   Kubernetes, so a compromised rag-api can't either.
> - `&locked-down` is a YAML anchor: one security context, written once, used by both containers.
> - Same settings as Compose: the environment variables are Step 17's; the hostnames (`rag-db`, `litellm`,
>   …) are the same thanks to the external-deps component.

- **`openbao-agent.hcl`** — the same job as the Compose agent (Step 28) but `auto_auth` uses `method "jwt"` at
  `auth/kubernetes-jwt`, `role = "rag-api"`, reading the token from `/var/run/secrets/openbao/token` with
  `remove_jwt_after_reading = false` (the kubelet owns that file and keeps refreshing it). The four templates
  (`rag_db.json`, `audit_db.json`, `rag_api_gateway_key`, `rag_api_opa_token`) are identical to Step 28's
  (tested): only the login method changes.
- **`service.yaml`** — Service `rag-api`, port 8000 → `http`; selector filled in by the labels.
- **`pdb.yaml`** — PodDisruptionBudget `minAvailable: 1`.
- **`networkpolicy.yaml`** — `rag-api`: ingress only on 8000; egress only to DNS (53 UDP/TCP) and the ports of
  the Compose services (5432, 4000, 8181, 8200, 8180, 4317; by port, because their addresses belong to
  OrbStack). Plus `default-deny` for everything else in the namespace.

### 3 · The link to Compose, and the local overlay

- **`deploy/components/external-deps/`** — a Kustomize *Component* with six `ExternalName` Services
  (`rag-db`, `litellm`, `opa`, `openbao`, `keycloak`, `otel-collector`), each a DNS alias for
  `host.docker.internal`, where Compose publishes each service's port. So `<name>.rag.svc` resolves to your Mac
  and rag-api's settings don't change.
- **`deploy/envs/local/kustomization.yaml`** — `namespace: rag`; the base plus the component; the image
  `rag-api` → `ghcr.io/owner/rag-platform/rag-api` with `digest: sha256:<digest>` (set by
  `just promote local sha256:…`); and a JSON patch that adds
  `OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=k8s-local` and `imagePullSecrets: [ghcr-pull]`.

> **READING THE OVERLAY**
> - `namespace: rag` puts everything there.
> - `images:` is where the version lives: one name, one digest. `just promote` edits exactly this line.
> - `patches:` adds what only this environment needs: its name for telemetry, and the pull secret.
> - A second environment (`envs/staging`, say) is a copy of this folder with its own digest and patches; the
>   base doesn't change.

```bash
just k8s-render envs/local | less       # the exact YAML Argo CD will apply
```

> **TWO THINGS TO CHECK ON YOUR MAC**
> Two properties depend on OrbStack's internals, which the guide couldn't test. Both have a check:
> - **Can pods reach Compose?** `just k8s-deps-check` connects to each service through
>   `host.docker.internal`. If one says `FAIL`, the service's port is published only to 127.0.0.1 in a way
>   the cluster can't reach; publish that port on the OrbStack bridge or move the client config to the service's
>   `*.orb.local` name.
> - **Are NetworkPolicies enforced?** OrbStack's network plugin is Flannel, which by itself doesn't enforce
>   them. `just k8s-netpol-check` tells you. If they aren't, the policies are still worth having (they document
>   intent and will apply on a real cluster), but don't count on them here.

### 4 · Pods log in to OpenBao with their own identity

In Compose (Step 28) you handed the agent a wrapped secret ID, and a restarted agent needed a new one. In
Kubernetes, every pod already has an identity: its service account. The kubelet gives the agent a short-lived
token signed by the cluster, and OpenBao checks it with the cluster's public key.

`scripts/vault_setup.py` gains:

- `K8sRole` and `K8S_ROLES = (K8sRole("rag-api", "rag", "rag-api", ("rag-api",)),)`, `K8S_MOUNT = "kubernetes-jwt"`,
  `K8S_AUDIENCE = "openbao"`;
- `jwks_to_pem(jwks)` — the cluster's token-signing public keys (from `/openid/v1/jwks`) as PEM;
- `k8s_trust(bao, jwks, issuer)` — enables a `jwt` auth method at `kubernetes-jwt/` (once), configures it with
  `jwt_validation_pubkeys` and `bound_issuer`, and writes one role per `K8sRole`: `user_claim: sub`,
  `bound_subject: system:serviceaccount:<namespace>:<account>`, `bound_audiences: [openbao]`, the policies,
  `token_ttl: 1h`, `token_max_ttl: 4h`, `token_type: service`;
- the subcommand `k8s-trust --jwks FILE --issuer URL`.

`infra/config/openbao/policies/platform-admin.hcl` gets `path "auth/kubernetes-jwt/*"` (create, read, update,
delete, list) so your day-to-day admin login can run it.

```bash
just vault-login
just vault-k8s-trust
```

```text
$ just vault-k8s-trust
ok: jwt auth at kubernetes-jwt/
ok: trusts 1 cluster signing key(s), issuer https://kubernetes.default.svc.cluster.local
ok: 1 kubernetes role(s)
```

What such a token says (`kubectl create token rag-api -n rag --audience openbao`, decoded): `aud: ["openbao"]`,
`iss: https://kubernetes.default.svc.cluster.local`, `sub: system:serviceaccount:rag:rag-api`, an `exp`, and a
`kubernetes.io` block with the namespace and service account name and uid. Logging in with it gives policies
`["default", "rag-api"]`, `lease_duration: 3600`, `metadata.role: rag-api`. Logging in with an ordinary API
token (audience: the Kubernetes API) gives `HTTP 400 … invalid audience (aud) claim: audience claim does not
match any expected audience`.

> **WHY THE JWT METHOD, NOT OPENBAO'S KUBERNETES METHOD**
> OpenBao also has a `kubernetes` auth method. It asks the cluster's API ("is this token valid?", a TokenReview)
> on every login, so OpenBao must reach the API server and hold a token allowed to ask. Our OpenBao lives in
> Compose, outside the cluster. The JWT method checks the same token offline, against the cluster's public
> signing key, and needs no connection and no credential towards Kubernetes.
> The trade-off: a token from a deleted service account stays valid until it expires. That's why the token lives only
> 10 minutes. If the cluster's signing key changes (a cluster reset), logins fail until `just vault-k8s-trust` runs
> again; the runbook says so.

> **STEP 28'S APPROLE STAYS**
> rag-api in Compose still uses AppRole (the cluster and Compose can run side by side while you switch). Once
> Kubernetes is the only place rag-api runs, remove the `rag-api-agent` service and the AppRole from
> `vault_setup.py`.

### 5 · Test it against a real API server

A YAML file can be valid YAML and still be refused by Kubernetes, or accepted and then ignored. So the tests
start a real `kube-apiserver` and `etcd` (no nodes: nothing is scheduled, but every object is validated and
admitted exactly as in a cluster).

- **`tests/kube.py`** — `ApiServer`: creates a cluster CA, an admin client certificate (group
  `system:masters`) and a service-account signing key with `openssl` (what kubeadm or OrbStack would create
  for you), starts etcd and kube-apiserver on free ports (RBAC, the cluster issuer, the signing key), writes a
  kubeconfig, waits for `/readyz`, and offers `kubectl()`, `apply()` (server-side) and `get()`.
- **`tests/test_k8s.py`** — renders each kustomization with the real `kubectl kustomize` (filling the
  `<digest>` placeholders with zeros, as you would before applying) and:
  - *static checks:* every kustomization renders; every container is digest-pinned, read-only,
    capability-free and limited; the sidecar, its config and OpenBao's role agree on account, audience, mount
    path and role name; Compose's and Kubernetes' agents render the same files; projects keep the app in its
    namespace, all Applications use one repository and `main`, self-heal everywhere, `cluster` never prunes and
    syncs before `rag-api-local`; the vendored Argo CD manifest matches its recorded hash;
  - *against the API server:* rag-api is accepted by Pod Security and both policies (with no warnings); a tag,
    another registry, another owner, root, a writable filesystem, a mounted API token, a privileged container
    and a Deployment without limits are each refused with a clear message; a bare Pod without limits gets the
    LimitRange default; namespaces without the label are unaffected; Argo CD's full release manifest applies,
    our projects and Applications are accepted by its CRDs, and an Application with a typo is refused by the
    schema.
- **`tests/test_vault.py`** (added) — against the Step 28 OpenBao server and the same kind of API server: a
  pod's token logs in and gets only `rag-api`'s secrets; another account in the namespace, the same name in
  another namespace, a token meant for the Kubernetes API, and a token with identical claims signed by a
  different key are refused; trusting the cluster again changes nothing; and the REAL
  `deploy/base/rag-api/openbao-agent.hcl` logs in with a token file, renders all four files, leaves the token
  file in place, and the database login it got works.
- **`tests/test_promote.py`** and **`tests/test_k8s_secrets.py`** — the promotion script and the two
  Kubernetes Secrets (see sections 6 and 7).

> **READING THE TESTS**
> - Static checks on the rendered YAML: every kustomization renders; every container is digest-pinned, read-
>   only, capability-free and limited; the sidecar, its config and OpenBao's role agree on account, audience,
>   mount path and role name; Compose's and Kubernetes' agents render the same files.
> - Against the API server: rag-api is accepted by Pod Security and both policies; a tag, another registry,
>   another owner, root, a writable filesystem, a mounted API token, a privileged container and a Deployment
>   without limits are each refused with a clear message; namespaces without the label are unaffected.
> - Argo CD: its full release manifest applies, our projects and Applications are accepted by its CRDs, and an
>   Application with a typo is refused by the schema.
> - Waiting for policies: a new admission policy takes a moment to load (the API server refreshes them about
>   once a second). The fixture waits until a known-bad canary is refused. The guide's first version didn't, and a test
>   passed a tagged image through: a real-world lesson about applying policies and workloads in the same
>   breath (which is what sync waves are for).

```bash
just k8s-check           # renders + the Kubernetes tests
just audit-test          # everything: 263 passed in the guide's count
```

What the API server answered, for the record:

```text
$ kubectl kustomize deploy/cluster | kubectl apply --server-side -f -
namespace/rag serverside-applied
resourcequota/rag-quota serverside-applied
limitrange/rag-defaults serverside-applied
validatingadmissionpolicy.admissionregistration.k8s.io/rag-images-pinned serverside-applied
validatingadmissionpolicy.admissionregistration.k8s.io/rag-workloads-hardened serverside-applied
validatingadmissionpolicybinding.admissionregistration.k8s.io/rag-images-pinned serverside-applied
validatingadmissionpolicybinding.admissionregistration.k8s.io/rag-workloads-hardened serverside-applied
```

```text
$ kubectl create -f same-pod-with-a-tag.yaml
Error from server (Forbidden): error when creating "STDIN": pods "tagged" is forbidden:
ValidatingAdmissionPolicy 'rag-images-pinned' with binding 'rag-images-pinned' denied request: images
must come from ghcr.io/owner/ or quay.io/openbao/ and be pinned by @sha256 digest; got:
ghcr.io/owner/rag-platform/rag-api:latest

$ kubectl create -f same-pod-as-root.yaml
Error from server (Forbidden): error when creating "STDIN": pods "as-root" is forbidden: violates
PodSecurity "restricted:v1.36": runAsNonRoot != true (pod or containers "openbao-agent", "rag-api"
must set securityContext.runAsNonRoot=true), runAsUser=0 (pod must not set runAsUser=0)

$ kubectl create -f same-pod-with-an-api-token.yaml
The pods "with-token" is invalid: : ValidatingAdmissionPolicy 'rag-workloads-hardened' with binding
'rag-workloads-hardened' denied request: set automountServiceAccountToken false (mount a projected
token explicitly if needed)
```

### 6 · Argo CD

Argo CD is installed from its release manifest, kept in the repository (**vendored**) so that installs need no
network, upgrades are reviewable diffs, and the content is pinned by SHA-256 (tested).

- **`deploy/argocd/install/kustomization.yaml`** — namespace `argocd`; `namespace.yaml` plus
  `upstream/install.yaml` (`# v3.5.5, sha256 90dc9094…5f50`); the three images pinned by digest
  (`quay.io/argoproj/argocd` of `:v3.5.5`, `ghcr.io/dexidp/dex` of `:v2.45.1`,
  `public.ecr.aws/docker/library/redis` of `:8.2.3-alpine`); and three patches:
  - **`argocd-cm.yaml`** — `timeout.reconciliation: 180s`; `exec.enabled: "false"` (no shell into pods from the
    web UI); `kustomize.buildOptions: --load-restrictor LoadRestrictionsRootOnly`; and the Lua health check for
    `argoproj.io/Application` from Argo CD's documentation, so a sync wave waits until the previous
    Applications are *Healthy*, not merely created.
  - **`argocd-rbac-cm.yaml`** — `policy.default: role:readonly`, `scopes: "[groups]"`.
  - **`argocd-cmd-params-cm.yaml`** — `controller.diff.server.side: "true"` (Kubernetes computes the diff:
    fewer false "OutOfSync").
- **`deploy/argocd/install/namespace.yaml`** — namespace `argocd`, Pod Security `enforce: baseline`,
  `warn: restricted`.
- **`deploy/argocd/apps/projects.yaml`** — two AppProjects (sync wave −2):
  - **platform**: Argo CD itself and the guard rails; destinations `argocd` and `rag`; may create only
    Namespace, ValidatingAdmissionPolicy(Binding), CustomResourceDefinition, ClusterRole and ClusterRoleBinding
    cluster-wide.
  - **rag**: namespace `rag` only, no cluster-wide objects at all, and blacklisted from `ResourceQuota` and
    `LimitRange` (the app can't loosen its own limits). A commented `syncWindows` example lets you restrict
    syncs to working hours.
- **`deploy/argocd/apps/{argocd,cluster,rag-api-local}.yaml`** — the three Applications, all from
  `git@github.com:owner/rag-platform.git` at `main`, automated with `selfHeal: true`, `ServerSideApply=true`,
  `PruneLast=true`, and retries (5, backoff 10 s × 2 up to 3 min):
  - `argocd` (wave −1, `deploy/argocd/install` → `argocd`, prune on, no finalizer): Argo CD manages its own upgrades.
  - `cluster` (wave −1, `deploy/cluster` → `rag`, **prune off**, no finalizer): never auto-delete a namespace.
  - `rag-api-local` (wave 1, `deploy/envs/local` → `rag`, project `rag`, prune on, with the
    `resources-finalizer.argocd.argoproj.io` finalizer).
- **`deploy/argocd/apps/kustomization.yaml`** lists those four files.
- **`deploy/argocd/root.yaml`** — the ONE thing you apply by hand (`just k8s-bootstrap`): Application `root`
  pointing at `deploy/argocd/apps`. Everything else Argo CD creates from git: the "app of apps" pattern.

> **READING THE ARGO CD SETUP**
> - Two projects: `platform` (Argo CD itself, the guard rails; may create the few cluster-wide kinds they need)
>   and `rag` (namespace `rag` only, no cluster-wide objects, may not touch quotas or limits). An app can
>   never do more than its project allows.
> - App of apps: you apply `root.yaml` once; it points at `deploy/argocd/apps/`, which holds the other
>   Applications. Adding an app is a pull request.
> - Argo CD manages itself (`argocd` app): upgrading it is `just argocd-vendor v3.x.y` and a pull request.
> - Sync waves: projects (−2), then Argo CD and the guard rails (−1), then rag-api (1). The custom health check
>   in `argocd-cm` (from Argo CD's documentation) makes a wave wait until the previous Applications are
>   Healthy, not merely created.
> - `selfHeal: true` everywhere: a hand-made change is reverted. `prune: true` removes what was deleted
>   from git, except for the guard rails (`prune: false`: deleting the `rag` namespace by accident would delete
>   everything in it).
> - Finalizer only on rag-api: deleting the `rag-api-local` Application removes its objects; deleting `argocd`
>   or `cluster` must not.
> - `ServerSideApply=true`: Kubernetes merges the changes itself (needed for Argo CD's large CRDs too).
> - Images by digest: fill in the three `<digest>` values (Step 9 method: `docker buildx imagetools inspect
>   quay.io/argoproj/argocd:v3.5.5`), as everywhere else in the platform.

On the test API server, after applying install, projects and apps, `kubectl -n argocd get
applications,appprojects` lists the Applications `argocd`, `cluster`, `rag-api-local` (and `root`) and the
projects `platform` and `rag`.

**Two Kubernetes Secrets are needed, and only two:** Argo CD's read-only deploy key for the repository, and a
read-only package token to pull your private images. Everything else secret comes from OpenBao.
**`scripts/k8s_secrets.py`** prints them as YAML for `kubectl apply -f -`:

- `pull-secret` → Secret `ghcr-pull` in `rag`, type `kubernetes.io/dockerconfigjson`, for `ghcr.io` only, from
  `GHCR_USER` and `GHCR_READ_TOKEN`;
- `repo-secret <git@github.com:owner/repo.git>` → Secret `repo-rag-platform` in `argocd` with the label
  `argocd.argoproj.io/secret-type: repository` (how Argo CD finds repository credentials), from
  `ARGOCD_DEPLOY_KEY`; it refuses something that isn't an SSH private key or an SSH URL.

Values come from environment variables (your SOPS env), never from command-line arguments, which end up in
shell history and process lists; refusals never print the value.

```bash
# once: create the keys
ssh-keygen -t ed25519 -N "" -C argocd-rag-platform -f /tmp/argocd-deploy-key
gh repo deploy-key add /tmp/argocd-deploy-key.pub --title argocd-local     # read-only by default
sops secrets/dev.enc.env      # add ARGOCD_DEPLOY_KEY (the private key), GHCR_USER, GHCR_READ_TOKEN
rm /tmp/argocd-deploy-key /tmp/argocd-deploy-key.pub
```

For `GHCR_READ_TOKEN`, create a fine-grained personal access token with only read access to packages, and an
expiry date.

The `justfile` gains a "Kubernetes and GitOps (Step 29)" section with `kube := "kubectl --context orbstack"`
and `repo_ssh := "git@github.com:owner/rag-platform.git"`:

| Recipe | What it does |
|---|---|
| `just k8s-up` | `orb start k8s` and show the node |
| `just k8s-render [path]` | what a kustomization renders (exactly what Argo CD applies) |
| `just k8s-check` | render all five kustomizations and run the Kubernetes tests |
| `just k8s-diff [path]` | what would change in the cluster if this were applied now (read-only) |
| `just k8s-bootstrap` | once per cluster: Argo CD, its repository key, the projects, then the root app |
| `just k8s-repo-secret` / `just k8s-pull-secret` | the two Secrets, from your SOPS env straight into `kubectl apply` |
| `just k8s-status` | Applications (sync, health, revision) and the rag-api pods |
| `just argocd-ui` | copies the first admin password to your clipboard (never prints it) and port-forwards https://localhost:8443 |
| `just vault-k8s-trust` | fetches the cluster's JWKS and issuer and runs `vault_setup.py k8s-trust` (after every cluster reset) |
| `just k8s-deps-check` | a busybox pod checks each Compose service through its ExternalName |
| `just k8s-netpol-check` | a deny-all namespace: can a pod still resolve a name? Tells you whether NetworkPolicies are enforced |
| `just promote env digest` | verify, change one line, commit on a branch, push, open a pull request |
| `just argocd-vendor version` | fetch a new Argo CD release manifest, record its SHA-256 |
| `just k8s-scan` | Trivy misconfiguration scan of the rendered `cluster` and `envs/local` |

```bash
# once per cluster
just k8s-bootstrap         # Argo CD, its repository key, the projects, the root app
just k8s-pull-secret
just k8s-status            # until everything is Synced / Healthy
just argocd-ui             # https://localhost:8443, user admin
```

> **CHANGE THE INITIAL ADMIN PASSWORD, THEN DELETE ITS SECRET**
> Argo CD creates a random admin password in `argocd-initial-admin-secret`. `just argocd-ui` copies it to
> your clipboard (never printing it). Change it in the UI (User Info → Update Password), then delete that Secret. In
> a team, sign in with Keycloak (OIDC) instead and switch the local admin off (`admin.enabled: "false"` in
> `argocd-cm`).

### 7 · Promote, and roll back

**`scripts/promote.py`** sets the rag-api digest for one environment and nothing else: it accepts only
`sha256:<64 lower-case hex>`, finds `deploy/envs/<env>/kustomization.yaml` (or lists the known environments),
requires exactly one `images` entry named `rag-api`, and edits that one line *as text* so every comment and all
formatting stay exactly as they are (or adds a `digest:` line if the entry has none). It re-reads the YAML to
make sure the change landed, and returns the previous digest (none for the `<digest>` placeholder).

```bash
just promote local sha256:3f1c…       # a new release is out (Step 27's release run shows its digest)
```

The recipe:

1. verifies the image: keyless signature from your `release.yml` on `main`, and its provenance (`just
   image-verify`, Step 27);
2. changes one line (the digest; comments and formatting untouched, tested);
3. commits with the previous digest in the message, pushes a branch, opens a pull request.

CI runs on it like on any change; you review a one-line diff; merging deploys. Argo CD notices within three
minutes, the Deployment rolls out new pods, and the old ones go only once the new ones are ready.

**Rollback is `git revert` of that commit**, through the same flow. Not Argo CD's Rollback button: it refuses while
automated sync is on, and the root app would switch automation back on from git anyway. The revert is fast
and leaves a record of what was undone and why.

> **WHY A PERSON RUNS THE PROMOTION**
> A workflow could open the pull request automatically. But a pull request created with GitHub Actions' own token
> doesn't trigger CI (GitHub's rule against workflow loops), so it could never pass the required checks. The clean
> fix is a GitHub App token; until then, `just promote` from your Mac keeps a person deciding what goes live,
> which is right for one environment anyway.

### 8 · Scan the manifests, in CI

Trivy (Step 27) also checks Kubernetes manifests. The first run found nine things: KSV-01010 (MEDIUM) on the
agent ConfigMap (the word `error_on_missing_key`), KSV-0108 (HIGH) on each of the six ExternalName Services,
and KSV-0125 (MEDIUM) on both containers ("untrusted registry").

None of them is a mistake, but each is a decision, so each is written down in **`.trivyignore.yaml`** with its
reason and an expiry date (2027-04-01), after which it must be looked at again:

- **KSV-0108** — ExternalName Services point at the Compose services on this Mac. The known risk
  (CVE-2020-8554) needs an attacker who can create Services; only Argo CD can (git review) in namespace `rag`.
  Replace with in-cluster services when Postgres etc. move.
- **KSV-0125** — Trivy's default "trusted registries" list doesn't know ours. Our own admission policy allows only
  `ghcr.io/owner/` and `quay.io/openbao/`, by digest.
- **KSV-01010** — false positive: the agent's ConfigMap contains the setting name `error_on_missing_key`, no
  secret.

`just k8s-scan` then reports 0 misconfigurations for both `cluster.yaml` and `envs-local.yaml`, and it is now part
of `ci-supply-chain`. In `.github/workflows/ci.yml`, the checks job installs `kubectl kube-apiserver etcd` beside
the other pinned tools (so the 43 tests run in CI), and the supply-chain job installs `kubectl` for the scan.
`ci/tools.yaml` pins all three from the envtest bundle (Kubernetes 1.36.2, etcd 3.6.8): one archive per
platform, the same URL and SHA-256 for each, with `member: controller-tools/envtest/<binary>`.

### 9 · The runbook

**`docs/runbooks/kubernetes.md`** starts from "git is the truth": the fix for almost everything is a commit. It
covers: rolling back a bad release (`git log -- deploy/envs/local`, `git revert`, and why not the Rollback button);
an application OutOfSync or Degraded (admission denials → fix git, never weaken `deploy/cluster/`; pods stuck in
`Init:0/1` → read the agent's log: signature/audience errors mean `just vault-k8s-trust`, connection errors mean
OpenBao is down or Compose unreachable, permission errors mean a policy change; `ImagePullBackOff`;
`CrashLoopBackOff`); someone changing the cluster by hand; Argo CD broken or deleted (`just k8s-bootstrap` again,
nothing lost); and a reset cluster (`k8s-up`, `k8s-bootstrap`, `k8s-pull-secret`, `vault-k8s-trust`, `k8s-status`).

### 10 · Record the decision

```bash
just adr "Run rag-api on Kubernetes, deployed by Argo CD from git"
```

**`docs/adr/0029-run-rag-api-on-kubernetes-deployed-by-argo-cd-from-git.md`** records the decision, the
alternatives (Helm, Flux, push-based deploys, Kyverno/Gatekeeper/policy-controller, OpenBao's Kubernetes auth
method, kind/k3d/minikube), the consequences and when to revisit it.

```bash
git add -A
git commit -m "feat(deploy): Kubernetes manifests, admission policies, Argo CD GitOps, OpenBao Kubernetes login"
git push -u origin feat/kubernetes
gh pr create --fill && gh pr checks --watch
gh pr merge --squash --delete-branch
git switch main && git pull
just promote local sha256:<the latest release digest>    # the first GitOps deployment
```

## Benefits

- **Deploying is reviewing:** every change to what runs is a pull request; the git log is the deployment history.
- **Drift can't build up:** hand-made changes are reverted; a deleted Argo CD is re-created from git with
  nothing lost.
- **Only what you built runs:** digest-pinned images from your registry, verified at promotion; everything else is
  refused at the door.
- **Least privilege by default:** non-root, read-only, no capabilities, no API token, memory-only secrets, project
  boundaries.
- **No secret handover:** pods log in to OpenBao with their own identity; restarts and new replicas need no
  human.
- **Zero-downtime rollouts, fast rollbacks.**
- **Tested like code:** manifests are rendered and admitted by a real API server in CI.

## Drawbacks and risks

- **Much more to learn and run:** Kubernetes, Kustomize and Argo CD each have depth. The runbook covers
  the common failures; expect to read logs.
- **Two worlds for now:** rag-api in Kubernetes, its dependencies in Compose, linked by DNS aliases whose
  reachability depends on OrbStack.
- **One node is not high availability:** two replicas protect against a crashed pod, not a crashed Mac.
- **Signature checked once:** at promotion. Someone with cluster-admin could still run a pinned but unsigned
  image in another namespace.
- **Admission policies are only as good as their scope:** they cover namespaces with the label; a new
  namespace needs it too.
- **Token trust is offline:** a token from a deleted account stays valid for up to 10 minutes; a cluster reset needs
  `just vault-k8s-trust`.

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| Kustomize (our choice) | Plain YAML plus declared patches, built into kubectl | Your own apps, few environments, readable diffs |
| Helm | Templated packages (charts) with values | Publishing software for others, many install options, third-party apps |
| Argo CD (our choice) | GitOps controller with a UI, projects, app of apps | Teams that want to see and control syncs |
| Flux | GitOps controllers without a built-in UI, very composable | Automation-heavy setups, image automation |
| Kyverno / OPA Gatekeeper | Policy engines as admission webhooks, with mutation, reports | Many rules, many teams, policy reports |
| Sigstore policy-controller / Kyverno verifyImages | Check image signatures inside the cluster | Several people can deploy; regulated environments |
| External Secrets Operator / OpenBao agent injector / CSI driver | Other ways to get secrets into pods | ESO: sync into Kubernetes Secrets; injector: automatic sidecars |
| kind / k3d / minikube / Talos | Other local or self-managed Kubernetes | Multi-node testing, CI clusters, bare metal |
| EKS / GKE / AKS | Managed Kubernetes in the cloud | Production: managed control plane, nodes across zones |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| One person, one Mac (this guide) | This step: OrbStack, Kustomize, Argo CD, built-in admission policies, JWT login to OpenBao |
| Small team, one cluster | Same, plus Argo CD SSO with Keycloak, branch protection on `deploy/`, a staging overlay, Argo CD notifications |
| Several teams | One AppProject per team, Kyverno or Gatekeeper with policy reports, in-cluster signature verification, ApplicationSets |
| Production in a cloud | Managed Kubernetes across zones, CloudNativePG or a managed database, OpenBao (or the cloud's secret manager) with Kubernetes auth, progressive delivery (Argo Rollouts) gated by Step 26's evaluations |
| Regulated | All of the above, plus audit logs of the API server and Argo CD shipped to write-once storage (like Step 23), and periodic access reviews |

## Common mistakes

- `kubectl apply` by hand in a GitOps cluster: Argo CD reverts it, or worse, you switch self-heal off "for a
  moment" and forget.
- Tags instead of digests, and `imagePullPolicy: Always` as a substitute for pinning.
- Secrets in git or in ConfigMaps; API tokens auto-mounted into every pod.
- No resource limits: one leaky pod takes memory from the models.
- Liveness probes that check dependencies: a database blip then restarts every pod. Our probes check only
  the process.
- One giant Argo CD project with access to everything.
- Applying policies and workloads at the same moment and assuming the policies already apply.
- Trusting NetworkPolicies on a plugin that ignores them.
- Accepting scanner findings silently instead of writing down why, with an expiry.

## Done when

- [ ] `kubectl --context orbstack version` shows a server of 1.33 or newer
- [ ] `just k8s-check` and `just audit-test` (263 passed in the guide's count) are green; `just k8s-scan` is clean
- [ ] `just k8s-bootstrap` done; `just k8s-status` shows `root`, `argocd`, `cluster`, `rag-api-local` Synced and Healthy
- [ ] `just vault-k8s-trust` done; `kubectl --context orbstack -n rag get pods` shows 2/2 Running for both rag-api pods
- [ ] `just k8s-deps-check` all `ok`; you know whether `just k8s-netpol-check` says enforced
- [ ] A search through the Kubernetes rag-api works (`http://rag-api.rag.svc.cluster.local:8000` from your Mac)
- [ ] `kubectl --context orbstack -n rag scale deploy rag-api --replicas=5` is undone by Argo CD within minutes
- [ ] A promotion and its revert both went through pull requests
- [ ] ADR-0029 is merged

## Recap

> **RECAP**
> rag-api now runs the way production services run:
> - **declared, not commanded:** Kustomize describes it, Argo CD keeps the cluster matching `main`, hand-made
>   changes are undone
> - **guarded at the door:** Pod Security "restricted" and two admission policies refuse unpinned images, root
>   containers, missing limits and API tokens, before anything is stored
> - **secret-free pods:** an OpenBao Agent sidecar logs in with the pod's short-lived service account token,
>   checked offline against the cluster's key
> - **deployed by pull request:** a verified digest is promoted with a one-line change; rolling back is a revert
> - **tested for real:** 43 new tests, most against a real Kubernetes API server, plus a manifest scan in CI

### Where you are now

That completes the platform half of Project 0. Over 29 steps, starting from an empty Mac, you've built the
plumbing that a security reviewer, an auditor and an on-call engineer would all recognise:

| Layer | What you built |
|---|---|
| Foundations (1–6) | A reproducible Mac, uv workspaces, containers, git with signed commits and ADRs, quality gates, SOPS secrets |
| Models (7–10) | Local Qwen models on MLX, embeddings and reranking, one gateway with keys, budgets and logs |
| Data (11–15) | Postgres with pgvector, Qdrant, OpenSearch, object storage, Valkey: each with least-privilege roles |
| Identity and policy (16–18) | Keycloak sign-in, a token-checking API, and authorisation as tested code (OPA) |
| Observability (19–22) | Traces, metrics, logs, SLOs and alerts, and LLM-specific tracing |
| Audit and governance (23–25) | A tamper-evident audit log, a versioned prompt registry, model and data cards with lineage |
| Quality and delivery (26–29) | Evaluation gates, a signed and attested supply chain, dynamic secrets, and GitOps on Kubernetes |

What's still missing is the RAG itself: nothing yet turns documents into searchable chunks, combines vector
and keyword search, reranks, writes cited answers or guards them. Every project would otherwise build those
parts again, slightly differently. So the guide continues:

- **Phase H · RAG core (Steps 30–35):** a shared `rag-core` library of switchable components (ingestion,
  retrieval, ranking, answers, guardrails) and the main RAG architectures, all chosen in one `rag.yaml` file.
- **Phase I · Production & reuse (Steps 36–38):** data lifecycle and threat model, staging and production with
  promotion gates, and a template that starts any new RAG project with all of this already wired.

Some of the ideas listed here before (a second environment, progressive delivery with evaluation gates) are
now part of Step 37.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `deploy/cluster/kustomization.yaml` | The guard rails as one kustomization, applied before any app |
| `deploy/cluster/namespace-rag.yaml` | Namespace `rag`: Pod Security `restricted` (pinned to v1.36) and the label that switches our policies on |
| `deploy/cluster/quota.yaml` | ResourceQuota (the namespace's ceiling) and LimitRange (per-container defaults and maximum) |
| `deploy/cluster/policy-images.yaml` | Admission policy: images only from `ghcr.io/owner/` or `quay.io/openbao/`, pinned by digest |
| `deploy/cluster/policy-workloads.yaml` | Admission policy: requests + memory limit, read-only root filesystem, no automounted API token |
| `deploy/base/rag-api/kustomization.yaml` | Shared labels, the resources, the agent ConfigMap generator and the OpenBao image |
| `deploy/base/rag-api/serviceaccount.yaml` | The pod's identity, with no API token mounted |
| `deploy/base/rag-api/deployment.yaml` | rag-api (2 replicas, zero-downtime rollouts, locked down) with the OpenBao Agent native sidecar |
| `deploy/base/rag-api/openbao-agent.hcl` | The agent config: JWT login with the projected token, the same four templates as Step 28 |
| `deploy/base/rag-api/service.yaml` | A stable name and port for the rag-api pods |
| `deploy/base/rag-api/pdb.yaml` | Never voluntarily take the last pod away |
| `deploy/base/rag-api/networkpolicy.yaml` | Default deny, then only DNS and the Compose services' ports |
| `deploy/components/external-deps/kustomization.yaml` | The Kustomize component linking the cluster to Compose |
| `deploy/components/external-deps/services.yaml` | Six ExternalName Services: the Compose names inside the cluster |
| `deploy/envs/local/kustomization.yaml` | The local overlay: namespace, the rag-api digest, telemetry name, pull secret |
| `deploy/argocd/install/kustomization.yaml` | Argo CD from the vendored release manifest (hash recorded), images by digest, our settings |
| `deploy/argocd/install/upstream/install.yaml` | Argo CD v3.5.5's release manifest, unchanged (SHA-256 checked by a test) |
| `deploy/argocd/install/namespace.yaml` | Namespace `argocd` with Pod Security baseline |
| `deploy/argocd/install/argocd-cm.yaml` | Reconcile every 3 min, no web exec, root-only kustomize loads, Application health for waves |
| `deploy/argocd/install/argocd-rbac-cm.yaml` | Read-only by default |
| `deploy/argocd/install/argocd-cmd-params-cm.yaml` | Server-side diff |
| `deploy/argocd/apps/projects.yaml` | The `platform` and `rag` AppProjects: Argo CD's permission boundaries |
| `deploy/argocd/apps/argocd.yaml` | Argo CD manages itself |
| `deploy/argocd/apps/cluster.yaml` | The guard rails, wave −1, never pruned |
| `deploy/argocd/apps/rag-api-local.yaml` | rag-api in namespace `rag`, wave 1 |
| `deploy/argocd/apps/kustomization.yaml` | Lists the projects and Applications for the root app |
| `deploy/argocd/root.yaml` | The one Application applied by hand: the app of apps |
| `scripts/vault_setup.py` (changed) | `K8sRole`, `jwks_to_pem`, `k8s_trust` and the `k8s-trust` subcommand |
| `infra/config/openbao/policies/platform-admin.hcl` (changed) | The admin may manage `auth/kubernetes-jwt/*` |
| `scripts/k8s_secrets.py` | Prints the only two Kubernetes Secrets (image pull, repository key) from env vars |
| `scripts/promote.py` | Changes exactly the digest line of one environment |
| `tests/kube.py` | A real etcd + kube-apiserver for tests |
| `tests/test_k8s.py` | 22 tests: rendering, hardening, agreement with OpenBao, Argo CD, and real admission |
| `tests/test_promote.py` | 9 tests: one line changes, only digests, unknown environments, missing digest lines |
| `tests/test_k8s_secrets.py` | 5 tests: shape and labels of both Secrets; refusals never print values |
| `tests/test_vault.py` (changed) | 7 tests: Kubernetes logins against real OpenBao + a real API server, and the real pod agent config |
| `tests/test_ci_tools.py` (changed) | The tool manifest now includes kubectl, kube-apiserver and etcd |
| `justfile` (changed) | The Kubernetes and GitOps recipes; `k8s-scan` in `ci-supply-chain` |
| `ci/tools.yaml` (changed) | kubectl, kube-apiserver, etcd 1.36.2 from the envtest bundle, checksum-pinned |
| `.github/workflows/ci.yml` (changed) | Installs the Kubernetes binaries in the checks and supply-chain jobs |
| `.trivyignore.yaml` | The three accepted Trivy findings, each with a reason and an expiry |
| `.pre-commit-config.yaml` (changed) | Multi-document YAML allowed; the vendored Argo CD manifest exempt from the 1 MB limit |
| `.env.example` (changed) | `GHCR_USER`, `GHCR_READ_TOKEN`, `ARGOCD_DEPLOY_KEY` placeholders |
| `docs/runbooks/kubernetes.md` | What to do when an app is OutOfSync, pods are stuck, Argo CD is gone or the cluster was reset |
| `docs/adr/0029-run-rag-api-on-kubernetes-deployed-by-argo-cd-from-git.md` | ADR-0029 |

## Notes for this repository

- **Validation here (Linux container, no OrbStack):** every kustomization was rendered with the pinned
  `kubectl kustomize` (kubectl 1.36.2 from the envtest bundle, whose SHA-256 values match the guide exactly) and
  validated with kubeconform (core schemas for Kubernetes 1.33 and the CRDs catalog for Argo CD objects). All 43
  new tests pass here, against a real `kube-apiserver` + `etcd` 1.36.2 and, for the OpenBao tests, the Step 28
  OpenBao server and a throwaway Postgres. `just k8s-scan` reports the same nine findings as the guide without
  the ignore file and none with it. A real cluster (OrbStack, or kind) was not started: `k8s-up`, `k8s-bootstrap`,
  `k8s-deps-check`, `k8s-netpol-check`, `argocd-ui` and `promote` need your Mac, your GitHub repository and
  OrbStack.
- **Vendored Argo CD manifest:** `deploy/argocd/install/upstream/install.yaml` was downloaded from the
  `v3.5.5` tag; its SHA-256 (`90dc9094…5f50`) matches the hash the guide records. It is about 1.9 MB, so
  `.pre-commit-config.yaml` exempts exactly that file from the 1 MB `check-added-large-files` limit, and
  `check-yaml` now allows multi-document YAML (every Kubernetes manifest with `---` needs it).
- **Image digests:** the dex (`ghcr.io/dexidp/dex:v2.45.1`) and redis
  (`public.ecr.aws/docker/library/redis:8.2.3-alpine`) digests were looked up from their registries and filled in.
  `quay.io` is blocked by this environment's network policy, so the digests of `quay.io/argoproj/argocd:v3.5.5`
  and `quay.io/openbao/openbao:2.7.1` stay as the guide's `sha256:<digest>` placeholders; fill them in on your
  Mac with `docker buildx imagetools inspect <image:tag>` before bootstrapping (the tests fill placeholders with
  zeros, as the guide does). The rag-api digest in `deploy/envs/local` is set by your first `just promote`.
- **`owner`:** as in the guide, `ghcr.io/owner/`, `git@github.com:owner/rag-platform.git` and the justfile's
  `repo_ssh` use the placeholder `owner`; replace it with your GitHub owner in lower case everywhere it appears
  (including the admission policy's message).
- **Files the guide only summarises:** `tests/test_promote.py`, `tests/test_k8s_secrets.py` and the Kubernetes
  part of `tests/test_vault.py` (`k8s_token`, the `k8s_trusted` fixture, `jwt_login` and the refusal, forged-token,
  re-trust and pod-agent tests) are written from the guide's test list and descriptions; their names match the
  guide's output.
- **`jwks_to_pem`** skips non-RSA keys and, defensively, uses the public half if a JWKS ever contained a private
  RSA key, so the strict type checker is satisfied; behaviour for a normal cluster JWKS is exactly the guide's.
- **Secrets:** `ARGOCD_DEPLOY_KEY`, `GHCR_USER` and `GHCR_READ_TOKEN` are added to your SOPS file by hand;
  `.env.example` lists them as placeholders only. No key or token is committed.
