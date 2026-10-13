# Runbook: Kubernetes and Argo CD (Step 29)

Git is the truth. Argo CD makes the cluster match `main`; anything changed by hand is changed
back (self-heal). So the fix for almost everything is a commit, and the record is the git log.

## Roll back a bad release (minutes)

1. Find the promotion: `git log --oneline -- deploy/envs/local` (each one names the digest it
   replaced).
2. `git revert <commit>`, push, pull request, merge. Argo CD rolls the previous digest out.
3. Why not Argo CD's "Rollback" button? It refuses while automated sync is on, and the root app
   would switch automation straight back on from git. The revert IS the fast path, and it leaves
   a record of what was undone and why.

## An application is OutOfSync or Degraded

- `just k8s-status`, then open it in the UI (`just argocd-ui`): the diff shows exactly which field
  differs from git; the events show why a pod isn't healthy.
- **Sync failed, "admission webhook / ValidatingAdmissionPolicy … denied":** the manifest breaks
  a guard rail (the message names the rule and the value). Fix it in git; never weaken
  `deploy/cluster/` to get a deploy through without a reviewed reason.
- **Pods `Init:0/1` for minutes:** the OpenBao agent can't log in.
  `kubectl --context orbstack -n rag logs deploy/rag-api -c openbao-agent`:
  - `invalid audience` / `signature` / `no known key`: the cluster was reset or its signing key
    changed. Run `just vault-k8s-trust`.
  - `connection refused` / timeouts: OpenBao is down or sealed (`just vault-up`), or pods can't
    reach Compose (`just k8s-deps-check`).
  - `permission denied` on a path: a policy changed (`git log infra/config/openbao/policies`).
- **`ImagePullBackOff`:** the digest doesn't exist (typo in a promotion?) or the pull secret
  expired: `just k8s-pull-secret` with a fresh read-only token.
- **`CrashLoopBackOff`:** `kubectl --context orbstack -n rag logs deploy/rag-api -c rag-api --previous`.
  Usually a dependency (Keycloak, OPA, LiteLLM) is unreachable: `just k8s-deps-check`.

## Someone changed something in the cluster by hand

Argo CD reverts it within minutes (self-heal) and the UI shows what was changed. Find out who
(`kubectl` access is limited to you here; in a team, the cluster audit log), and if the change was
needed, make it in git.

## Argo CD itself is broken or was deleted

Nothing is lost: everything it manages is in git. `just k8s-bootstrap` installs it again and it
picks the applications back up. The running workloads keep running meanwhile.

## The whole cluster was reset (OrbStack → Reset Kubernetes)

1. `just k8s-up`
2. Fill in nothing new: `just k8s-bootstrap` (Argo CD + repository key + root app)
3. `just k8s-pull-secret` and `just vault-k8s-trust` (the new cluster has new signing keys)
4. `just k8s-status` until everything is Synced and Healthy.
