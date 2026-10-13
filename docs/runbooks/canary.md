# Runbook: canary releases (Argo Rollouts, Step 37)

**Normal flow.** Merging a promotion pull request changes the digest; Argo CD syncs; Argo Rollouts
starts the new release at 10% of pods, then 25%, 50%, 100%, waiting between steps while the
analysis (deploy/components/production/analysis-template.yaml) compares it with the stable release.

**Watch:** `kubectl argo rollouts get rollout rag-api -n rag --watch` (plugin) or the Argo CD UI.

**RagCanaryAborted** (the analysis failed and the canary was scaled to zero):
1. Which check failed: `kubectl -n rag get analysisrun -l rollouts-pod-template-hash` →
   `kubectl -n rag describe analysisrun <name>` shows each metric's measurements.
2. The stable release is still serving everyone: no customer impact beyond the canary's share.
3. Revert the promotion commit (pull request). Leaving an aborted rollout and merging a fix on top is
   also fine: a new digest starts a fresh canary.

**Manual controls (emergencies only; everything else through git)**
- Stop a rollout now: `kubectl argo rollouts abort rag-api -n rag`
- Skip the remaining steps (a verified hot fix): `kubectl argo rollouts promote rag-api -n rag --full`
  This is break-glass: note it in the incident log, like `just promote … "INC-…: reason"`.

**Low traffic.** With few answers per hour the analysis can't tell good from bad ("insufficient").
Staging passes on insufficient data (it has little traffic); prod fails safe. Lengthen the pauses
or send synthetic traffic (the evaluation questions) during the rollout.
