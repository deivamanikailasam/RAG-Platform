# Runbook: a secret has leaked (or might have)

1. **Revoke / rotate first, investigate second.** Change the value at its source
   (database, object storage, provider dashboard), then update it: `just secrets-edit`.
2. **Restart** the services that use it so the new value takes effect.
3. **Assess:** what could the secret access? Check service logs for use since the leak.
4. **Clean up:** if it was committed, remove it from history (`git filter-repo`) and
   force-push *only after* rotating; ask GitHub support to purge cached views if needed.
5. **If an age private key leaked:** generate a new key, update `.sops.yaml`,
   run `sops updatekeys`, and rotate EVERY value it could decrypt.
6. **Record** what happened and what changes prevent a repeat (ADR or postmortem).
