# secrets/

Encrypted platform dev secrets (Step 6). Everything in this folder except this README and
`.gitkeep` **must** be SOPS-encrypted; the `secrets-encrypted` pre-commit hook
(`scripts/check-sops-encrypted.sh`) refuses anything else, and `.sops.yaml` says who can open
files named `secrets/*.enc.env|yaml|yml|json`.

## First time on a machine

```bash
# 1. Make your age key pair (once per machine) and keep the private key private
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt        # prints: Public key: age1...
chmod 600 ~/.config/sops/age/keys.txt
export SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/keys.txt"   # .envrc does this via direnv

# 2. Put your PUBLIC key (age1...) into .sops.yaml in place of age1REPLACE_WITH_YOUR_PUBLIC_KEY

# 3. Generate random values for every service, encrypted immediately
just secrets-init                                 # = scripts/new-dev-secrets.sh -> secrets/dev.enc.env
cat secrets/dev.enc.env                           # names readable, every value ENC[AES256_GCM,...]
git add secrets/dev.enc.env .sops.yaml
```

The list of names the file holds is in [`../.env.example`](../.env.example) (dummy values only).
If you ever write a secrets file by hand, encrypt it **in place before `git add`**:

```bash
sops --encrypt --in-place secrets/<name>.enc.env
```

## Everyday use (no plaintext on disk)

| Job | Command |
|---|---|
| List the names (never values) | `just secrets-keys` |
| Edit / change one value | `just secrets-edit` (= `sops secrets/dev.enc.env`), then restart the service |
| Run one command with the secrets | `just with-secrets docker compose up -d` (= `sops exec-env secrets/dev.enc.env '…'`) |
| Refresh the internal data key | `sops --rotate --in-place secrets/dev.enc.env` |
| Add / remove a recipient | edit `.sops.yaml`, then `sops updatekeys secrets/dev.enc.env` |

Never run `sops -d … > .env`. If a secret leaks, follow
[`docs/runbooks/secret-leak.md`](../docs/runbooks/secret-leak.md).

> This repository does not ship `secrets/dev.enc.env`: it can only be produced with the owner's own
> age key, so each machine creates it with `just secrets-init` as above.
