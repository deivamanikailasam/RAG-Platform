# Step 6 · Local secrets handling

*Step 6 of 38 · Phase A · Workstation*

## At a glance

| | |
|---|---|
| **Goal** | Decide where every password, key and token lives, and set up a safe way to store, share, use and rotate them, so no secret is ever written in plain text in your code, your git history, your container images or your logs. |
| **Time** | About 75–90 minutes. |
| **You'll end up with** | age + SOPS encrypting the platform's dev secrets in a file that's safe to commit; your personal tokens in the macOS Keychain; containers receiving secrets as files, not environment variables; a Python settings class that masks secrets; a pre-commit guard, a leak-response runbook and ADR-0006. |
| **New words** | Secret, plaintext, ciphertext, encryption, key pair, age, SOPS, envelope encryption, data key, recipient, Keychain, environment variable, secret file, `SecretStr`, rotation, revocation. |

## The big idea

> **ANALOGY · A LOCKBOX ANYONE CAN CARRY, KEYS ONLY YOU HOLD**
> The platform needs about a dozen passwords (database, file store, cache, sign-in server, gateway…). You could
> write them on a sticky note: a plaintext `.env` file. But sticky notes get photographed, copied and left behind.
> Instead, put the passwords in a lockbox (an encrypted file). The lockbox is safe to carry around, even in git,
> because it can only be opened by someone holding the right key. Only your Mac (and later, your CI server) has
> that key. When the platform starts, the lockbox is opened in memory, the passwords are handed directly to the
> services that need them, and nothing is ever written down in plain text.

**SOPS** is the lockbox tool. **age** makes and uses the keys. The **macOS Keychain** is a separate personal safe
for tokens that belong to *you*, not to the platform.

## What we're doing

1. Install age and SOPS, and create your age key pair.
2. Write `.sops.yaml`, the rules saying who can open which encrypted files.
3. Generate strong random passwords for every service the platform will run, straight into an encrypted
   `secrets/dev.enc.env`.
4. Learn to view, edit, use and rotate secrets without writing plain text to disk.
5. Add a pre-commit guard that refuses unencrypted files in `secrets/`.
6. Pass secrets to containers as files (`/run/secrets/…`), and prove they don't appear in `docker inspect`.
7. Read secrets in Python with pydantic-settings and `SecretStr`, which hides them from logs.
8. Store personal tokens (e.g. Hugging Face) in the macOS Keychain, loaded by direnv.
9. Add `.env.example`, `just` recipes, a secret-leak runbook and ADR-0006.

## Why we're doing this

> **WHY THIS MATTERS**
> Leaked credentials are one of the most common ways real systems are breached. Bots scan public repositories
> for keys within minutes of a push, and deleting a file doesn't remove it from git history. In a RAG platform, one
> leaked database password exposes every document you've indexed, possibly including personal or confidential
> data.

| Risk | How this step prevents it |
|---|---|
| Passwords committed to git (forever, in history) | Only encrypted values are committed; a hook blocks anything else in `secrets/` |
| A plaintext `.env` left on disk, synced to cloud backup, or shared in chat | Secrets are decrypted only in memory, for one command at a time |
| Weak or reused passwords (`postgres` / `admin123`) | Every value is randomly generated, 32+ characters |
| Secrets visible in `docker inspect`, crash dumps or logs | Containers receive files, not environment variables; Python masks values with `SecretStr` |
| Nobody knows what to do after a leak | A runbook: revoke and rotate first, then clean up |
| No way to share secrets safely with CI or a teammate | Add their public key as a recipient; no password is ever sent |

> **IN A COMPANY**
> Security frameworks treat secrets management as a core control. OWASP's Top 10 for LLM Applications lists
> sensitive information disclosure; ISO 27001 and SOC 2 require controlled access to credentials; and auditors
> ask: *Where are secrets stored? Who can read them? How are they rotated? How would you know if one leaked?*
> By the end of this step you can answer all four.

## Key ideas

### Three homes for secrets

| | Personal tokens | Platform dev secrets | Production secrets |
|---|---|---|---|
| **Where** | macOS Keychain | SOPS + age file in git | HashiCorp Vault |
| **What** | GitHub (`gh`), Hugging Face, other accounts tied to *you* | DB, object store, Redis, Keycloak, LiteLLM, Langfuse passwords | Short-lived, generated on demand, audited per access |
| **How it's protected** | Never shared; encrypted by macOS, unlocked by your login | Shared with the repo, but values encrypted; key stays on approved machines | Nobody sees long-lived passwords; automatic expiry and revocation |
| **When** | Now (Step 6) | Now (Step 6) | Later (Step 28) |

Moving left to right, secrets become *more shared, more automated and shorter-lived*.

*Figure 18 of the guide: Three homes for secrets. Personal tokens go in the Keychain; shared platform dev secrets
go in an encrypted file; production secrets will come from Vault in Step 28.*

### The words, in plain English

| Term | Plain-English meaning |
|---|---|
| Secret | Any value that grants access: a password, API key, token, private key or encryption key |
| Plaintext / ciphertext | Readable text / the scrambled, encrypted version of it |
| Encryption | Scrambling data so only someone with the right key can unscramble it |
| Key pair (public / private key) | Two matching keys. Anyone can use the public key to lock something; only the private key can unlock it. You share the public key freely and guard the private one. |
| age | A small, modern, simple encryption tool with short keys (`age1…`). Designed as a safer, easier replacement for GPG. |
| SOPS | "Secrets OPerationS": encrypts the *values* in YAML, JSON or `.env` files while leaving the *names* readable, so diffs and reviews still make sense |
| Recipient | Someone (or a machine) whose public key can open the file: you, CI, a teammate |
| Envelope encryption | Values are locked with a random data key, and the data key is locked separately for each recipient. Adding a person never means re-encrypting every value by hand. |
| macOS Keychain | The Mac's built-in encrypted password store, unlocked by your login |
| Environment variable | A named value handed to a program when it starts (`DB_PASSWORD=…`). Convenient, but easy to leak (see below). |
| Secret file / `/run/secrets` | A secret delivered to a container as a small file in memory, the standard pattern in Docker and Kubernetes |
| Rotation | Replacing a secret with a new value on a schedule, or immediately after a suspected leak |
| Revocation | Making an old secret stop working, e.g. deleting an API token |

### How SOPS keeps values safe while names stay readable

```
 Plaintext values                 Random data key                 secrets/dev.enc.env
 POSTGRES_PASSWORD=Xk3…   ──►     made fresh by SOPS      ──►     POSTGRES_PASSWORD=ENC[AES…]
 REDIS_PASSWORD=9fQ…   encrypt    AES-256-GCM                     REDIS_PASSWORD=ENC[AES…]
 LITELLM_MASTER_KEY=sk-…          locks each VALUE                sops_age__list_0__map_enc=…
                                                                  sops_mac=ENC[…]
                                        │                         safe to commit: names visible,
                                        │ data key is itself      values locked
                                        ▼ locked for each recipient
                you                   CI runner                  teammate
            age1… your Mac          age1… (Step 27)           age1… (optional)

   Only someone holding a matching PRIVATE key can unlock the data key, and then the values.
```

*Figure 19 of the guide: Envelope encryption in SOPS. A fresh data key locks the values; the data key is locked
separately for each recipient's public key.*

So there are two layers of lock. The **data key** is one random key that SOPS invents for the file and uses to
lock every value (with AES-256-GCM, a fast, standard cipher). The data key itself is then locked once per
**recipient**, using that recipient's age public key, and those locked copies are stored at the bottom of the
file. To open the file you need *any one* of the recipients' private keys. Adding a teammate therefore only means
locking the same data key one more time, for their public key.

### Environment variables vs secret files

| `environment: DB_PASSWORD=…` | `/run/secrets/db_password` |
|---|---|
| visible in `docker inspect` | not shown in `docker inspect` |
| inherited by every child process | not inherited by child processes |
| often dumped in crash reports and debug logs | file permissions limit who can read it |
| readable via `/proc/<pid>/environ` | same pattern as Kubernetes / Vault |
| simple; works with almost any image | app must support `*_FILE` or a secrets dir |
| **OK for non-secret config** | **Preferred for secrets** |

*Figure 20 of the guide: Why secrets should reach containers as files. Environment variables leak in more ways;
plain configuration can still use them.*

> **IN PLAIN ENGLISH · THE 12-FACTOR RULE, REFINED**
> The well-known 12-factor app guideline says "keep config in the environment, not in code". That's right for
> *settings* (log level, model name, port). For *secrets*, the modern refinement is: deliver them as files where you
> can, and treat any environment variable holding a secret as short-lived and private to one process.

## How to do it

All commands run on your Mac, from the project folder (the root of this repository):

```bash
cd ~/dev/rag-platform
git switch -c feat/local-secrets
```

### 1 · Install age and SOPS, and create your key pair

Two lines are appended to [`bootstrap/Brewfile`](../../bootstrap/Brewfile):

```ruby
# ---- Secrets (Step 6) ----
brew "age"                  # modern file encryption; makes the key pair SOPS uses
brew "sops"                 # encrypts values inside .env / YAML / JSON files, keeps names readable
```

Then install them and make your key pair:

```bash
just bootstrap
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt           # prints: Public key: age1...
chmod 600 ~/.config/sops/age/keys.txt               # only you can read the private key
age-keygen -y ~/.config/sops/age/keys.txt           # shows the public key again, any time
```

> **WATCH OUT · BACK UP THE PRIVATE KEY, AND PROTECT IT**
> `~/.config/sops/age/keys.txt` contains your private key (the line starting `AGE-SECRET-KEY-`).
> - Back it up in a password manager (1Password, Bitwarden, Apple Passwords) as a secure note. If you lose it, you
>   can't decrypt anything it locked. Dev secrets can be regenerated, but it's still painful.
> - Never commit it, paste it into chat, or copy it to cloud-synced folders.
> - The public key (`age1…`) is safe to share and goes into `.sops.yaml`.

SOPS looks for the key in different default places on different systems, so tell it exactly where it is. direnv
will do this for the project (part 8). For now, set it in your shell too:

```bash
echo 'export SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/keys.txt"' >> ~/.zshrc
source ~/.zshrc
```

(The same line is kept in the reference copy [`bootstrap/home/.zshrc`](../../bootstrap/home/.zshrc).)

### 2 · Write `.sops.yaml`: who can open what

[`.sops.yaml`](../../.sops.yaml) holds the encryption rules. Replace `age1REPLACE…` with *your* public key from
part 1:

```yaml
# Encryption rules. Files matching path_regex are encrypted for every listed age recipient.
creation_rules:
  - path_regex: ^secrets/.*\.enc\.(env|ya?ml|json)$
    age: >-
      age1REPLACE_WITH_YOUR_PUBLIC_KEY
    # Later: add the CI runner's public key (Step 27), comma-separated, then run `sops updatekeys <file>`
```

Any file under `secrets/` whose name ends `.enc.env`, `.enc.yaml`, `.enc.yml` or `.enc.json` is encrypted for
every public key listed under `age:`. Because SOPS reads this file, you never have to type the recipients on the
command line.

### 3 · Generate the platform's dev secrets, encrypted from the start

[`scripts/new-dev-secrets.sh`](../../scripts/new-dev-secrets.sh) creates strong random values for every service
the coming steps will run, and encrypts the file immediately:

- it refuses to run if `secrets/dev.enc.env` already exists (so you can't overwrite real secrets by accident);
- `umask 077` makes the brief plaintext version readable by you only;
- a `trap` deletes the file on exit **unless** it contains `sops_mac=` (the sign that encryption finished), so a
  failure half-way never leaves plaintext behind;
- `rand()` produces 32 random letters and digits from `openssl rand`;
- it writes the names, grouped by the step that will use them (data stores in Steps 11–15, identity in Step 16,
  the gateway in Step 9, observability in Steps 20 and 22, and a `DEMO_TOKEN` for this step). The LiteLLM master
  key gets an `sk-` prefix because LiteLLM requires it; the Langfuse encryption key is 64 hex characters
  (`openssl rand -hex 32`) because that is the format Langfuse expects;
- finally `sops --encrypt --in-place` locks it.

```bash
chmod +x scripts/new-dev-secrets.sh
scripts/new-dev-secrets.sh              # or: just secrets-init
cat secrets/dev.enc.env                 # look: names readable, every value is ENC[AES256_GCM,...]
```

> **WHAT YOU SHOULD NOTICE**
> The file still says `POSTGRES_PASSWORD=` in plain sight, so anyone reviewing a change can see *which* secret
> changed, but the value is unreadable. At the bottom are SOPS's own lines (`sops_age__…`, `sops_mac=…`): the
> data key locked for your public key, and a tamper seal (MAC) that fails if anyone edits the ciphertext by hand.

### 4 · View, edit, use and rotate: without plaintext on disk

```bash
sops --decrypt secrets/dev.enc.env | cut -d= -f1         # list the NAMES only (safe to show)
export EDITOR="nano"                                     # or "code --wait" for VS Code
sops secrets/dev.enc.env                                 # opens decrypted in your editor; re-encrypts on save
sops exec-env secrets/dev.enc.env 'echo "token length: ${#DEMO_TOKEN}"'   # use secrets in ONE command
```

> **TIP · `sops exec-env` IS THE EVERYDAY TOOL**
> It decrypts in memory, starts one command with the secrets as environment variables, and they disappear
> when that command ends. Nothing is written to disk, and your normal shell never sees them. From Step 11
> onward, the whole stack starts this way: `sops exec-env secrets/dev.enc.env 'docker compose up -d'`.

Rotation (new values) and re-keying (who can decrypt) are different jobs:

| Job | Command | When |
|---|---|---|
| Change one secret's value | `sops secrets/dev.enc.env`, edit, save, then restart the service that uses it | Scheduled rotation, or one value exposed |
| Refresh the internal data key | `sops --rotate --in-place secrets/dev.enc.env` | Periodically, or after removing a recipient |
| Add or remove a recipient | Edit `.sops.yaml`, then `sops updatekeys secrets/dev.enc.env` | New CI runner, teammate joins or leaves |

> **WATCH OUT · REMOVING A RECIPIENT IS NOT ENOUGH**
> Old versions of the file are still in git history, and the removed key can still open them. If a key is lost or
> compromised, change the actual secret *values* too, not just the recipients.

### 5 · Guard the `secrets/` folder with a pre-commit hook

[`scripts/check-sops-encrypted.sh`](../../scripts/check-sops-encrypted.sh) receives the staged files from
`secrets/` and fails if any of them lacks SOPS's tamper seal. It recognises all three formats: `sops_mac=` at the
start of a line (`.env`), `mac: ENC[` (YAML) and `"mac": "ENC[` (JSON). Markdown files and `.gitkeep` are
skipped, so the folder can carry a README.

```bash
#!/usr/bin/env bash
# Fail if any file passed in (from secrets/) is not SOPS-encrypted.
set -euo pipefail
status=0
for f in "$@"; do
  case "$f" in *.md|*/.gitkeep) continue ;; esac
  if ! grep -qE '^sops_mac=|^[[:space:]]*mac: ENC\[|"mac": "ENC\[' "$f"; then
    echo "NOT ENCRYPTED: $f   ->   run: sops --encrypt --in-place $f"
    status=1
  fi
done
exit $status
```

It is wired into [`.pre-commit-config.yaml`](../../.pre-commit-config.yaml) under `repo: local → hooks`:

```yaml
      - id: secrets-encrypted
        name: files in secrets/ are SOPS-encrypted
        entry: scripts/check-sops-encrypted.sh
        language: system
        files: ^secrets/
```

gitleaks (from Step 5) would otherwise flag SOPS ciphertext, because encrypted values look random by design.
[`.gitleaks.toml`](../../.gitleaks.toml) keeps gitleaks' default rules but allowlists the encrypted files:

```toml
# Use gitleaks' default rules, but don't flag SOPS ciphertext (it looks random by design).
[extend]
useDefault = true

[allowlist]
description = "SOPS-encrypted files"
paths = ['''^secrets/.*\.enc\.(env|ya?ml|json)$''']
```

Test the guard:

```bash
chmod +x scripts/check-sops-encrypted.sh
echo "OOPS=plaintext" > secrets/oops.enc.env
git add secrets/oops.enc.env && git commit -m "chore: test"     # blocked: NOT ENCRYPTED
git rm --cached secrets/oops.enc.env && rm secrets/oops.enc.env
```

### 6 · Give secrets to containers as files

[`infra/compose/secrets-demo.yaml`](../../infra/compose/secrets-demo.yaml) demonstrates the pattern every later
service will use:

```yaml
# Demonstrates the pattern every later service will use.
services:
  demo:
    image: alpine:3.20
    command: ["sh", "-c", "ls -l /run/secrets && echo \"length: $$(wc -c < /run/secrets/demo_token)\""]
    secrets: [demo_token]

secrets:
  demo_token:
    environment: DEMO_TOKEN   # value comes from the environment of the `docker compose` command
```

The top-level `secrets:` block says "the secret called `demo_token` takes its value from the `DEMO_TOKEN`
environment variable of the `docker compose` process". The service then lists `secrets: [demo_token]`, and
Compose mounts it as the file `/run/secrets/demo_token` inside the container. The `$$` is Compose's escape for a
literal `$`, so the shell inside the container (not Compose) runs `wc -c`.

```bash
sops exec-env secrets/dev.enc.env 'docker compose -f infra/compose/secrets-demo.yaml run --name secrets-demo demo'
# shows /run/secrets/demo_token and its length, never the value
docker inspect secrets-demo --format '{{json .Config.Env}}'     # DEMO_TOKEN does NOT appear
docker rm secrets-demo
```

The path of a secret at runtime:

```
 dev.enc.env  ──►  sops exec-env  ──►  docker compose  ──►  /run/secrets/x  ──►  app (pydantic)
 in git,           decrypts in         env vars exist       file inside          SecretStr: masked
 encrypted         memory with         only for this        container (not in    in logs and repr
                   your age key        one process          docker inspect)

 Never: a plaintext .env on disk, secrets baked into images, secrets in compose.yaml, or printed in logs.
```

*Figure 21 of the guide: The path of a secret at runtime. Encrypted in git, decrypted in memory for one command,
delivered into the container as a file, masked inside the app.*

> **TIP · HOW REAL SERVICES USE THIS**
> Most official images accept a `_FILE` variant of their password settings, e.g. Postgres reads
> `POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password`. You'll use exactly this from Step 11. If an image only
> accepts a plain environment variable, it still works, but note it as a known weakness.

### 7 · Read secrets safely in Python

```bash
uv add --package rag-common pydantic-settings
```

[`libs/rag-common/src/rag_common/settings.py`](../../libs/rag-common/src/rag_common/settings.py):

```python
"""Typed settings for every service. Secrets are SecretStr, so they never print by accident."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        secrets_dir="/run/secrets",  # container secret files are read from here
        extra="ignore",
    )

    environment: str = "dev"
    demo_token: SecretStr  # from env DEMO_TOKEN, or the file /run/secrets/demo_token


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

pydantic-settings fills each field from (in priority order) arguments, environment variables (case-insensitive,
so `DEMO_TOKEN` fills `demo_token`), and then files in `secrets_dir` named after the field. `extra="ignore"` means
unrelated environment variables don't cause errors. `get_settings()` is wrapped in `lru_cache` so settings are
read once per process and shared.

[`libs/rag-common/tests/test_settings.py`](../../libs/rag-common/tests/test_settings.py) proves the masking:

```python
def test_secret_is_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_TOKEN", "super-secret-value")
    settings = Settings()
    assert "super-secret-value" not in repr(settings)  # shows SecretStr('**********')
    assert settings.demo_token.get_secret_value() == "super-secret-value"
```

So mypy understands pydantic models, its plugin is added to the `[tool.mypy]` section of the root
[`pyproject.toml`](../../pyproject.toml):

```toml
plugins = ["pydantic.mypy"]
```

```bash
just test            # the guide says 2 passed; this repository has 3 (see Notes)
just typecheck       # no issues
```

> **IN PLAIN ENGLISH · SECRETSTR**
> `SecretStr` is a wrapper that prints as `**********`. If someone logs the whole settings object while
> debugging, the password doesn't end up in log files, which are often shipped to other systems and kept for
> months. To use the real value you must deliberately call `.get_secret_value()`, which makes every use easy
> to find in code review.

### 8 · Personal tokens in the macOS Keychain, loaded by direnv

Tokens that belong to you (Hugging Face for model downloads in Step 7, later others) don't belong in the shared
file. Store them in the Keychain:

```bash
security add-generic-password -a "$USER" -s "rag-platform/HF_TOKEN" -w      # prompts for the value; nothing in shell history
security find-generic-password -s "rag-platform/HF_TOKEN" -w | wc -c        # proves it's stored (prints length only)
```

Then make the project load it, plus the SOPS key location, whenever you `cd` into the repo. [`.envrc`](../../.envrc)
is committed: it contains no secret values, only *where to find them*.

```bash
# Loaded automatically by direnv inside this folder. Contains NO secret values.
[ -d .venv ] && source .venv/bin/activate
export SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/keys.txt"
# Personal token from the macOS Keychain (empty if not set):
export HF_TOKEN="$(security find-generic-password -s rag-platform/HF_TOKEN -w 2>/dev/null || true)"
```

```bash
direnv allow         # approve this .envrc (direnv asks again whenever it changes)
```

direnv's hook was added to `~/.zshrc` in Step 1, so from now on entering the folder activates the virtual
environment, points SOPS at your key and loads your token; leaving the folder unloads them.

### 9 · Document, automate and record

[`.env.example`](../../.env.example) lists the settings the platform expects, with no real values:

```text
# The settings this platform expects. NO real values here; real secrets live in
# secrets/dev.enc.env (encrypted) or the macOS Keychain (personal tokens).
POSTGRES_PASSWORD=<generated>
MINIO_ROOT_USER=rag-admin
...
LANGFUSE_ENCRYPTION_KEY=<64 hex characters>
DEMO_TOKEN=<generated>
HF_TOKEN=<from macOS Keychain>
```

Four recipes are added to the [`justfile`](../../justfile):

```make
# Create the encrypted dev secrets file (first time only)
secrets-init:
    scripts/new-dev-secrets.sh

# List secret NAMES (never values)
secrets-keys:
    sops --decrypt secrets/dev.enc.env | cut -d= -f1 | grep -v '^#' | grep .

# Edit secrets safely (decrypted only inside the editor)
secrets-edit:
    sops secrets/dev.enc.env

# Run any command with the dev secrets available:   just with-secrets docker compose up -d
with-secrets +cmd:
    sops exec-env secrets/dev.enc.env "{{cmd}}"
```

The leak runbook, [`docs/runbooks/secret-leak.md`](../runbooks/secret-leak.md), says what to do in order:

1. **Revoke / rotate first, investigate second.** Change the value at its source (database, object storage,
   provider dashboard), then update it: `just secrets-edit`.
2. **Restart** the services that use it so the new value takes effect.
3. **Assess:** what could the secret access? Check service logs for use since the leak.
4. **Clean up:** if it was committed, remove it from history (`git filter-repo`) and force-push *only after*
   rotating; ask GitHub support to purge cached views if needed.
5. **If an age private key leaked:** generate a new key, update `.sops.yaml`, run `sops updatekeys`, and rotate
   EVERY value it could decrypt.
6. **Record** what happened and what changes prevent a repeat (ADR or postmortem).

Record the decision:

```bash
just adr "Manage dev secrets with SOPS and age, personal tokens in Keychain"
```

This creates
[`docs/adr/0006-manage-dev-secrets-with-sops-and-age-personal-tokens-in-keychain.md`](../adr/0006-manage-dev-secrets-with-sops-and-age-personal-tokens-in-keychain.md),
filled in with the context (~12 credentials; plaintext `.env` files leak), the decision (SOPS + age, `sops
exec-env`, `/run/secrets`, `SecretStr`, Keychain + direnv, the pre-commit hook, Vault in Step 28), the
alternatives (plaintext `.env`, git-crypt, 1Password/Bitwarden CLI, Doppler/Infisical, Vault now), the
consequences and when to revisit it. Add ADR-0006 to the ADR index, then commit and merge:

```bash
git add -A
git status            # check: secrets/dev.enc.env is there and encrypted, no plaintext anywhere
git commit -m "feat(secrets): encrypted dev secrets with SOPS and age, file-based container secrets"
git push -u origin feat/local-secrets
gh pr create --fill && gh pr merge --squash --delete-branch
git switch main && git pull
```

## Benefits

- **Nothing readable leaves your Mac.** Git, backups and screenshots only ever see ciphertext.
- **Reviewable changes.** Names stay readable, so a PR shows *which* secret changed without revealing it.
- **Strong, unique passwords everywhere**, generated in seconds.
- **Easy sharing later.** Adding CI or a teammate means adding a public key; no password is ever sent.
- **Defence in depth.** Encryption, plus a pre-commit guard, plus gitleaks, plus file-based delivery, plus masked
  values in Python.
- **Production-shaped.** The `/run/secrets` file pattern is exactly what Kubernetes and Vault use later, so nothing
  has to be redesigned.

## Drawbacks and risks

- **The age private key is now the "master key".** Lose it and you regenerate everything; leak it and you rotate
  everything. Back it up, and protect the Mac (FileVault disk encryption, a strong login password).
- **Decrypted values live in memory while services run.** Anyone with admin access to your Mac or the containers
  could read them. Encryption protects data at rest, not a compromised machine.
- **Git history is permanent.** Ciphertext stays forever, so a later key compromise exposes old values too. That's
  why compromise means rotating *values*, not just keys.
- **Long-lived static secrets.** These passwords don't expire on their own. Vault's short-lived, auto-expiring
  credentials (Step 28) are the real fix for production.
- **Not every image supports `_FILE`.** Some secrets will have to be environment variables; document each
  exception.
- **More moving parts.** age, SOPS, direnv and Keychain each need to be understood. The `just` recipes hide most of
  that day to day.

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| **SOPS + age (our choice)** | Encrypted values in files, keys as simple age pairs | Solo or small teams, GitOps, secrets that live next to code |
| SOPS + cloud KMS (AWS KMS, GCP KMS, Azure Key Vault) | Same files, but the key lives in a cloud key service with access logs and IAM | Teams on a cloud provider who want audited, centrally revocable keys |
| git-crypt | Transparently encrypts whole files in git | Simple setups; you don't need readable names or per-person access |
| Password-manager CLIs (1Password `op run`, Bitwarden) | Secrets stay in your password manager and are injected per command | Teams already using a password manager; great developer experience |
| Doppler / Infisical (Infisical is open source) | A central secrets dashboard with environments, rotation and audit | Many services and environments; you want a UI and integrations |
| HashiCorp Vault / OpenBao | A secrets server: dynamic short-lived credentials, leasing, audit | Production, regulated environments, databases with auto-rotating users (Step 28) |
| Cloud secret managers (AWS Secrets Manager, GCP Secret Manager, Azure Key Vault) | Managed secret storage tied to cloud identity | Workloads running on that cloud |
| Kubernetes Sealed Secrets / External Secrets Operator | Encrypted secrets in git for Kubernetes / sync from Vault or a cloud manager | Kubernetes GitOps (Step 29) |
| Plain `.env`, gitignored | Unencrypted file on your disk | Throwaway prototypes only, with fake or low-value credentials |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Solo learning lab or small team, secrets beside code | SOPS + age (this step) |
| Team on AWS, GCP or Azure | SOPS + cloud KMS, or the cloud's secret manager |
| Many apps and environments, non-specialist teams | Doppler / Infisical, or a password-manager CLI |
| Production in a regulated industry | Vault / OpenBao with dynamic secrets, short TTLs and audit logs, plus a hardware-backed root key (HSM/KMS) |
| Kubernetes GitOps | External Secrets Operator (from Vault or a cloud manager) or Sealed Secrets |
| A personal API token for your own account | macOS Keychain or your password manager |

## Common mistakes

- **Committing `.env` "just once".** It stays in history forever. If it happens, follow the runbook: rotate first.
- **Committing the age private key** or putting it in a cloud-synced folder.
- **Decrypting to a file** (`sops -d … > .env`) and forgetting it's there. Use `sops exec-env` instead.
- **Printing secrets while debugging** (`print(settings)`, `echo $PASSWORD`). Use `SecretStr`, and print lengths or
  names, not values.
- **Putting secrets in `compose.yaml`, Dockerfiles or image layers.** Anyone who can pull the image can read them
  (`dive` from Step 3 shows them).
- **Reusing one password for several services.** One leak opens everything. Generate one per service.
- **Removing a teammate's key without rotating values.** Old ciphertext in git is still readable with their key.
- **Treating "encrypted in git" as finished.** Rotation, access review and leak response are ongoing work.

## Done when

- [ ] `age` and `sops` are in the Brewfile and installed
- [ ] Your age key exists with `chmod 600`, and is backed up in a password manager
- [ ] `.sops.yaml` lists your public key
- [ ] `secrets/dev.enc.env` is committed, and `cat` shows only `ENC[…]` values
- [ ] `just secrets-keys` lists the names, and `sops exec-env … 'echo ${#DEMO_TOKEN}'` prints a length
- [ ] The `secrets-encrypted` hook blocked a plaintext file in `secrets/`
- [ ] The demo container read `/run/secrets/demo_token`, and `docker inspect` didn't show it
- [ ] `Settings` masks the secret in `repr`, and `just test` and `just typecheck` pass
- [ ] Your HF token is in the Keychain, and `.envrc` loads it (`echo ${#HF_TOKEN}` shows a length)
- [ ] `.env.example`, `docs/runbooks/secret-leak.md` and ADR-0006 are committed via a PR

## Recap

> **RECAP**
> Every secret now has one proper home:
> - personal tokens → macOS Keychain
> - shared platform dev secrets → SOPS + age-encrypted file in git
> - production secrets → Vault (Step 28)
>
> Secrets are decrypted only in memory (`sops exec-env`), reach containers as files, and stay masked in Python. A
> hook blocks plaintext, gitleaks watches for leaks, and a runbook says exactly what to do if one escapes. That
> completes Phase A: your workstation and repository are ready, and Phase B starts serving the models.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| [`bootstrap/Brewfile`](../../bootstrap/Brewfile) | `age` and `sops` added under "Secrets (Step 6)". |
| [`bootstrap/home/.zshrc`](../../bootstrap/home/.zshrc) | Reference copy now also exports `SOPS_AGE_KEY_FILE`. |
| [`.sops.yaml`](../../.sops.yaml) | Encryption rules: `secrets/*.enc.(env\|yaml\|yml\|json)` for the listed age recipients (placeholder public key). |
| [`scripts/new-dev-secrets.sh`](../../scripts/new-dev-secrets.sh) | Generates random values for every service and encrypts them straight into `secrets/dev.enc.env`. |
| [`scripts/check-sops-encrypted.sh`](../../scripts/check-sops-encrypted.sh) | Pre-commit guard: fails for any file in `secrets/` without a SOPS MAC. |
| [`.pre-commit-config.yaml`](../../.pre-commit-config.yaml) | New local hook `secrets-encrypted` on `^secrets/`. |
| [`.gitleaks.toml`](../../.gitleaks.toml) | gitleaks default rules, with SOPS-encrypted files allowlisted. |
| [`secrets/README.md`](../../secrets/README.md), `secrets/.gitkeep` | The folder for encrypted secrets, with first-time and everyday commands (including the `sops --encrypt` command). |
| [`infra/compose/secrets-demo.yaml`](../../infra/compose/secrets-demo.yaml) | Demo service that receives `DEMO_TOKEN` as the file `/run/secrets/demo_token`. |
| [`.envrc`](../../.envrc) | direnv: activates `.venv`, sets `SOPS_AGE_KEY_FILE`, loads `HF_TOKEN` from the Keychain. No secret values. |
| [`.env.example`](../../.env.example) | Every setting the platform expects, with placeholder values only. |
| [`justfile`](../../justfile) | New `secrets-init`, `secrets-keys`, `secrets-edit` and `with-secrets` recipes. |
| [`libs/rag-common/src/rag_common/settings.py`](../../libs/rag-common/src/rag_common/settings.py) | Typed `Settings` (pydantic-settings) reading env vars or `/run/secrets` files; secrets as `SecretStr`. |
| [`libs/rag-common/tests/test_settings.py`](../../libs/rag-common/tests/test_settings.py) | Tests: the secret is masked in `repr`, and can be read from a secret file. |
| [`libs/rag-common/pyproject.toml`](../../libs/rag-common/pyproject.toml), [`uv.lock`](../../uv.lock) | `pydantic-settings` dependency, locked. |
| [`libs/rag-common/README.md`](../../libs/rag-common/README.md) | Short note on using `Settings`. |
| [`pyproject.toml`](../../pyproject.toml) | `plugins = ["pydantic.mypy"]` in `[tool.mypy]`. |
| [`docs/runbooks/secret-leak.md`](../runbooks/secret-leak.md) | What to do, in order, when a secret leaks. |
| [`docs/adr/0006-manage-dev-secrets-with-sops-and-age-personal-tokens-in-keychain.md`](../adr/0006-manage-dev-secrets-with-sops-and-age-personal-tokens-in-keychain.md) | ADR-0006, plus its row in the [ADR index](../adr/README.md). |
| [`README.md`](../../README.md) | Quick start mentions the secrets workflow. |
| [`docs/steps/step-06-local-secrets.md`](step-06-local-secrets.md) | This write-up. |
| [`docs/steps/README.md`](README.md), [`docs/glossary.md`](../glossary.md), [`CHANGELOG.md`](../../CHANGELOG.md) | Step 6 row, terms and entry added. |

## Notes for this repository

- **No `secrets/dev.enc.env` is committed.** It can only be produced honestly with the owner's own age key, so
  `.sops.yaml` keeps the guide's placeholder `age1REPLACE_WITH_YOUR_PUBLIC_KEY`. On the Mac: create the key, put the
  public key in `.sops.yaml`, run `just secrets-init` (or `scripts/new-dev-secrets.sh`), check `cat
  secrets/dev.enc.env` shows only `ENC[…]`, and commit it. The plaintext template of the names is
  [`.env.example`](../../.env.example); any hand-written secrets file is encrypted with
  `sops --encrypt --in-place secrets/<name>.enc.env` before `git add`. These instructions also live in
  [`secrets/README.md`](../../secrets/README.md), which the hook skips because it is Markdown.
- **`scripts/.gitkeep` moved to `secrets/.gitkeep`**: `scripts/` now has real files, and the empty `secrets/`
  folder needs the placeholder (the hook skips `*/.gitkeep`). `docs/runbooks/.gitkeep` was removed for the same
  reason.
- **Reference copy.** The `SOPS_AGE_KEY_FILE` line for `~/.zshrc` was appended to
  `bootstrap/home/.zshrc`, not to a real home directory.
- **An extra test.** `test_settings.py` has a second test,
  `test_secret_is_read_from_a_secret_file`, proving the `/run/secrets` path works (using a temporary folder as
  `_secrets_dir`). So `just test` reports **3 passed** here, not the guide's 2. pydantic-settings prints a
  harmless `UserWarning: directory "/run/secrets" does not exist` outside containers.
- **`just with-secrets` and `$` expansions.** The recipe wraps the command in double quotes, so a `${VAR}` in the
  arguments is expanded by the recipe's shell *before* SOPS adds the secrets. Use it for commands such as
  `just with-secrets docker compose up -d`; for a command that reads a secret variable itself, call
  `sops exec-env secrets/dev.enc.env '…'` directly with single quotes, as the guide does.
- **Branch and PR workflow.** This repository works on its own feature branch; the PR/merge is an owner action.
  The guide's commit message `feat(secrets): encrypted dev secrets with SOPS and age, file-based container
  secrets` is used for the tooling commit; the Python settings, ADR + runbook, and this write-up land in their
  own commits. ADR "Deciders" names the repository owner; the date is the guide's (2026-10-11).
- **Validation done here** (Linux container; sops 3.10.2 release binary and age 1.1.1, with a throwaway age key in
  a scratch folder outside the repo, never committed): `new-dev-secrets.sh` produced a file with every value
  `ENC[AES256_GCM,…]`, refused to overwrite it, and deleted the plaintext when `sops` was missing; `just
  secrets-keys` listed the 11 names; `sops exec-env … 'echo "token length: ${#DEMO_TOKEN}"'` printed 32; the
  `secrets-encrypted` hook blocked a plaintext `secrets/oops.enc.env` and passed real `.env`, YAML and JSON SOPS
  files; gitleaks passed with the allowlist; the Compose demo (via the `mirror.gcr.io` copy of `alpine:3.20`)
  listed `/run/secrets/demo_token`, printed `length: 32`, and `docker inspect` showed only `PATH` in
  `.Config.Env`. `uv run pytest` (3 passed), `uv run mypy` (no issues) and ruff pass. The Keychain commands and
  the `security` call in `.envrc` are macOS-only and were not run (on Linux the `|| true` leaves `HF_TOKEN` empty).
