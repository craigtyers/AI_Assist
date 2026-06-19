# Authentik Setup

This app supports two auth modes:

- `AUTH_MODE=dev` (temporary local role switch via `/__dev/role?...`)
- `AUTH_MODE=authentik` (OIDC JWT validation + role mapping)

## 1) Install dependency

`AUTH_MODE=authentik` requires `PyJWT`.

```bash
pip install PyJWT
```

## 2) Required environment variables

Set these before starting `app.py`:

```bash
export AUTH_MODE=authentik
export OIDC_ISSUER="https://auth.example.com/application/o/<your-provider-slug>/"
export OIDC_AUDIENCE="<your-client-id>"
export OIDC_JWKS_URL="https://auth.example.com/application/o/<your-provider-slug>/jwks/"
```

## 3) Role mapping (groups -> roles)

Defaults:

- `admin` if token group contains `recite-admins`
- `user` if token group contains `recite-users`
- otherwise `visitor`

Override with env vars:

```bash
export AUTH_ROLE_CLAIM="groups"
export AUTH_ROLE_MAP_LEVEL3="recite-admins"
export AUTH_ROLE_MAP_LEVEL2="recite-users"
```

You can provide multiple group names as comma-separated values:

```bash
export AUTH_ROLE_MAP_LEVEL3="recite-admins,platform-admins"
export AUTH_ROLE_MAP_LEVEL2="recite-users,internal-support"
```

## 4) Token input

The server looks for a token in this order:

1. `Authorization: Bearer <token>`
2. cookie name `access_token`

To change the cookie name:

```bash
export AUTH_ACCESS_TOKEN_COOKIE="your_cookie_name"
```

## 5) Start server

Example:

```bash
AUTH_MODE=authentik \
OIDC_ISSUER="https://auth.example.com/application/o/rag/" \
OIDC_AUDIENCE="rag-client" \
OIDC_JWKS_URL="https://auth.example.com/application/o/rag/jwks/" \
python3 app.py
```

Or with your startup script:

```bash
AUTH_MODE=authentik ./scripts/start_server.sh
```

## 6) Verify

### Check identity and role

```bash
curl -s http://127.0.0.1:5000/api/me
```

Expected keys include:

- `auth_mode` (`authentik`)
- `is_authenticated` (`true` with valid token)
- `role` (`visitor` / `user` / `admin`)

### Check role behavior quickly

- `visitor`: KB-only retrieval, no KB draft submission
- `user`: full retrieval, can submit KB drafts (pending approval)
- `admin`: admin actions allowed (`/api/kb/pending`, approve pending drafts)

## 7) Dev mode fallback

If you need to test without Authentik:

```bash
AUTH_MODE=dev ./scripts/start_server.sh
```

Then switch temporary role in browser:

- `/__dev/role?role=visitor`
- `/__dev/role?role=user`
- `/__dev/role?role=admin`
