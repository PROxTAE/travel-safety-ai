# `infra/keycloak/`

**เจ้าของ:** คนที่ 2 (02-api) ร่วมกับ Team Lead

The realm the public API verifies tokens against. `smart-travel-realm.json` is imported by the
`keycloak` service on startup (`--import-realm`, reading this folder).

## This is a local development realm

It contains **no credential of any kind**: no client secret, no user, no password. Everything in it
is public configuration. A staging or production realm is provisioned separately and must differ in
two ways:

1. **Delete `smart-travel-test-cli`.** It exists only so automated tests can obtain a real token
   without driving a browser, which means direct access grants are enabled on it. That is a
   password-grant surface and has no business existing anywhere but a developer's machine.
2. **Set `sslRequired` to `all`** and replace the `localhost:3000` redirect URIs and web origins.

## What the file configures, and why

| Piece | Why it is there |
| --- | --- |
| `web` client — public, PKCE, standard flow only | A single-page app cannot keep a secret, so it is a public client and PKCE is what makes the authorization-code flow safe for it. Direct access grants are **off**: the browser must never see a password grant. |
| `smart-travel-test-cli` — public, direct grants only | Lets the test suite sign in as a real user. No standard flow, no redirect URIs, no secret. |
| Audience mapper on both clients | Without it a token carries no `smart-travel-api` audience, and the API cannot tell a token meant for it from one meant for any other client in the realm. The API rejects the latter. |
| `travel` client scope, **optional** | The permission to call the API on the user's behalf. Optional rather than default so a client can genuinely ask for less — which makes "a valid token without the scope" a real case the API is tested against, rather than an impossible one. |
| `traveller` realm role, in the default composite | A user who has just signed up can use the product without an administrator granting anything. |
| `support` realm role, granted to nobody | Reserved for staff-facing endpoints so that `require_roles("support")` has something to check against later. |
| The six built-in client scopes, declared explicitly | Declaring `clientScopes` **replaces** Keycloak's built-ins rather than adding to them. Without `roles` a token has no `realm_access.roles`; without `profile` it has no `preferred_username` or `name`. Both were missing until they were listed here, and the failure is silent — the token is valid, it simply says less. |
| `offline_access` and `uma_authorization` realm roles | The default composite references them, and Keycloak resolves a composite's members during import, before it creates its own built-in roles. Omitting them fails the import with `Unable to find composite realm role`. |

## Changing the realm

`--import-realm` uses `IGNORE_EXISTING`: once the realm exists, editing this file does nothing.
To apply a change locally, delete the realm and restart:

```bash
# from the repository root, with the stack running
docker compose -f compose.yaml -f compose.dev.yaml --profile core --profile app run --rm api python -c "
import os, httpx
kc = os.environ['KEYCLOAK_BASE_URL'].rstrip('/')
tok = httpx.post(kc + '/realms/master/protocol/openid-connect/token', data={
    'grant_type': 'password', 'client_id': 'admin-cli',
    'username': os.environ['KEYCLOAK_ADMIN'], 'password': os.environ['KEYCLOAK_ADMIN_PASSWORD'],
}).json()['access_token']
print(httpx.delete(kc + '/admin/realms/smart-travel', headers={'Authorization': 'Bearer ' + tok}).status_code)
"

docker compose -f compose.yaml -f compose.dev.yaml --profile core restart keycloak
```

Deleting the realm deletes its users. That is fine locally — they are all throwaway — and is
exactly why this procedure must never be run anywhere else.

Verify the import took, and that a token still says what the API needs:

```bash
curl -fsS http://localhost:8080/realms/smart-travel/.well-known/openid-configuration | head -c 200
docker compose -f compose.yaml -f compose.dev.yaml --profile core --profile app run --rm api uv run pytest tests/test_keycloak_end_to_end.py
```

Those tests assert the things that break quietly: that the audience mapper fires, that `traveller`
is granted by default, and that a token without the `travel` scope is refused.

อ่านแผน: [`IMPLEMENTATION_PLANS/02_API_BACKEND_IMPLEMENTATION.md`](../../IMPLEMENTATION_PLANS/02_API_BACKEND_IMPLEMENTATION.md)
