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

## OpenBao's unseal keys and root token (Step 28)

`just vault-init` initialises OpenBao **once** and pipes its output straight into SOPS, so the
plaintext never touches the disk:

```bash
bao operator init -key-shares=3 -key-threshold=2 -format=json \
  | sops encrypt --filename-override secrets/openbao-init.enc.json --input-type json --output-type json /dev/stdin \
  > secrets/openbao-init.enc.json
```

The file you then commit, `secrets/openbao-init.enc.json`, has this shape **before encryption**
(dummy values shown; every real value becomes `ENC[AES256_GCM,…]`):

```json
{
  "unseal_keys_b64": ["<share 1, base64>", "<share 2, base64>", "<share 3, base64>"],
  "unseal_keys_hex": ["<share 1, hex>", "<share 2, hex>", "<share 3, hex>"],
  "unseal_shares": 3,
  "unseal_threshold": 2,
  "recovery_keys_b64": [],
  "recovery_keys_hex": [],
  "recovery_keys_shares": 0,
  "recovery_keys_threshold": 0,
  "root_token": "<s.… root token: revoked by `just vault-revoke-root` right after setup>"
}
```

- `just vault-unseal` decrypts it into a pipe (`sops decrypt … | vault_setup.py unseal`); 2 of the 3
  shares unseal the server after every restart.
- The root token is used once (`just vault-setup-first`) and then revoked (`just vault-revoke-root`);
  the copy in the file is then useless. Break-glass: `bao operator generate-root` with 2 shares.
- In a team, give each share to a different person, each encrypted to their own age key. Back up
  your age key separately from the OpenBao volume: whoever holds 2 shares and the volume can read
  every secret, and losing all shares loses the data for good.

> This repository does not ship `secrets/openbao-init.enc.json`: it is created per server with the
> owner's age key, as above. Never commit it unencrypted (the `secrets-encrypted` hook refuses).
