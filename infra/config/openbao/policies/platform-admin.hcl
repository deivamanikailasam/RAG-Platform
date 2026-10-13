# Day-to-day administration by a person (Step 28), instead of the root token.
# Be clear about what this is: someone who can write policies could grant themselves anything,
# so it is NOT a wall against a malicious admin. What it buys: no root token in daily use, every
# action tied to a named login in the audit log, and no accidental reading of secret values.
# It cannot seal/unseal, change audit devices (they live in server.hcl) or generate a root token.

# Engines and auth methods: switch on, tune, list
path "sys/mounts/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "sys/mounts" {
  capabilities = ["read", "list"]
}

path "sys/auth/*" {
  capabilities = ["create", "read", "update", "delete", "sudo"]
}

path "sys/auth" {
  capabilities = ["read", "list"]
}

# See which audit devices exist (setup refuses to run without one)
path "sys/audit" {
  capabilities = ["read", "sudo"]
}

# Policies, leases (look up, revoke one, revoke many)
path "sys/policies/acl/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "sys/leases/lookup/*" {
  capabilities = ["list", "update", "sudo"]
}

path "sys/leases/revoke" {
  capabilities = ["update"]
}

path "sys/leases/revoke-prefix/*" {
  capabilities = ["update", "sudo"]
}

# Database connections and roles; rotate the admin password. NOT database/creds/*
path "database/config/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "database/roles/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "database/rotate-root/*" {
  capabilities = ["update"]
}

# Machine and human logins
path "auth/approle/role/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "auth/userpass/users/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

# Secrets: write new values and manage versions, never read the values back
path "secret/metadata/*" {
  capabilities = ["read", "list", "delete"]
}

path "secret/data/*" {
  capabilities = ["create", "update"]
}
