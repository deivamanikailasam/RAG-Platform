# ADR-0006: Manage dev secrets with SOPS + age; personal tokens in the macOS Keychain

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** deivamanikailasam

## Context
The platform needs ~12 service credentials. Plaintext .env files leak through git history,
backups, screenshots and logs. Secrets must be shareable with CI later, rotatable, and auditable.

## Decision
Platform dev secrets live in secrets/dev.enc.env, encrypted with SOPS for age recipients listed
in .sops.yaml, and are decrypted only in memory via `sops exec-env`. Containers receive secrets
as files under /run/secrets (Compose secrets, *_FILE variables). Python reads them via
pydantic-settings SecretStr. Personal tokens live in the macOS Keychain, loaded by direnv.
A pre-commit hook rejects unencrypted files in secrets/. Production secrets move to Vault (Step 28).

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Plaintext .env (gitignored) | Simplest | Unshareable, leaks easily, no audit | Fails basic security |
| git-crypt | Transparent encryption | Whole-file, GPG-based, all-or-nothing access | SOPS diffs are reviewable |
| 1Password / Bitwarden CLI | Great UX, audit logs | Account dependency for every run | Good option; kept for personal use |
| Doppler / Infisical | Central dashboard, rotation | Extra service to run or pay for | Overkill for a local lab |
| Vault now | Production-grade | Heavy before anything runs | Planned for Step 28 |

## Consequences
+ Secrets can live in git safely; reviews show which secret changed.
+ No plaintext on disk; containers never expose secrets in inspect output.
- Losing the age private key means regenerating every dev secret.
- Some images only accept env vars; those are documented exceptions.

## Revisit when
A second developer or CI joins (add recipients), or Vault becomes available (Step 28).
