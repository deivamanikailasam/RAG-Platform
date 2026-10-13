# Runbook: KeycloakLoginFailuresHigh (warning)

**What it means:** more than 20 sign-ins failed in one realm in 10 minutes. Either someone is guessing
passwords, or a client is misconfigured (wrong secret, expired credentials) and retrying.
Keycloak's brute-force protection (Step 16) temporarily locks accounts, which limits the damage.

**Check first (5 minutes)**
1. Which errors? In Prometheus:
   `sum by (error, client_id) (increase(keycloak_user_events_total{event="login", error!=""}[10m]))`
   (`invalid_user_credentials` = wrong passwords; `invalid_client_credentials` = a machine client).
2. Keycloak admin console → realm `rag` → *Events* → *User events*, filter by type `LOGIN_ERROR`:
   which users and which IP addresses?
3. One user, many failures: probably a person who forgot a password, or a stuck script.
   Many users, one address: password guessing (credential stuffing).

**Likely causes**
- A rotated client secret not yet updated in `secrets/dev.enc.env` (machine clients retry forever).
- Password guessing against real accounts.
- A demo or test script looping with wrong credentials.

**Fix**
- Misconfigured client: update the secret (`just secrets-edit`) and restart the client.
- Guessing: confirm lockouts are working (*Users* → the user → *Brute force* status); block the source
  in front of Keycloak in production; tell the affected users; consider forcing a password reset.

**Close**
- Failures drop back to normal; the alert resolves when the 10-minute count falls under 20.
- For suspected attacks, record it in the security incident log (Step 23 audit trail).
