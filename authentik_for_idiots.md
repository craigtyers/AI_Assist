# Authentik for Idiots (Practical Guide)

This is a plain-English guide for wiring SSO auth in front of this app using Authentik.

Assumption: you understand basic SSO/OAuth concepts, but have not implemented Authentik before.

## 1) What Authentik Does

Authentik is your login authority.

- Your app does **not** handle passwords.
- Authentik handles login (via Google in your case).
- Your app receives trusted identity info (user/email/groups).
- Your app uses those groups to decide access level.

## 2) The Simple Mental Model

1. User opens your app URL.
2. Reverse proxy checks if user is logged in.
3. If not logged in, user is redirected to Authentik.
4. Authentik sends user to Google login.
5. Google authenticates user.
6. Authentik returns user to your app flow.
7. Proxy forwards identity headers to app.
8. App maps identity/groups to role and enforces permissions.

## 3) Recommended Architecture (Low Friction)

Keep your existing Python app.

Add:
- Reverse proxy (`nginx`/`traefik`/`caddy`)
- `oauth2-proxy` as OIDC client
- Authentik as identity provider (Google upstream)

Flow:

Internet -> Reverse Proxy -> oauth2-proxy auth check -> app.py

This avoids rewriting backend/frontend just for auth.

## 4) Why This Approach

- Minimal code changes
- Proven deployment pattern
- Authentication concerns separated from app logic
- App can focus on authorization + source scoping

## 5) Role Model We Want

- `guest` (no auth):
  - limited/public mode (KB-only retrieval)

- `recite_user` (authenticated):
  - full repo retrieval
  - can suggest KB article
  - cannot publish

- `admin` (authenticated):
  - full access
  - can approve/reject/publish KB suggestions
  - can run higher privilege actions

## 6) Authentik Setup Checklist

In Authentik:

1. Add Google as an authentication source.
2. Create OIDC provider/application for this app.
3. Create groups:
   - `ai-assist-recite-user`
   - `ai-assist-admin`
4. Assign users to groups.
5. Capture:
   - issuer URL
   - client ID
   - client secret

## 7) oauth2-proxy Setup Checklist

Configure oauth2-proxy with:

- OIDC provider: Authentik
- issuer URL: from Authentik provider
- client ID/secret: from Authentik app
- redirect URL: your oauth2 callback endpoint
- cookie secret: strong random value
- pass auth headers enabled

Typical headers sent upstream:

- `X-Auth-Request-User`
- `X-Auth-Request-Email`
- `X-Auth-Request-Groups`

## 8) Reverse Proxy (Nginx etc.) Role

Proxy should:

- route auth checks through oauth2-proxy
- pass only trusted auth headers to app
- optionally split public and internal routes/hosts

Example model:

- `assist-public.example.com`: anonymous allowed (guest policy)
- `assist-internal.example.com`: auth required

## 9) App-Side Authorization (Critical)

Do not rely on UI only.

In app backend:

1. Read trusted headers from proxy.
2. Map groups to role.
3. Enforce endpoint permissions.
4. Enforce source restrictions by role during retrieval.

Suggested mapping:

- if groups contains `ai-assist-admin` -> `admin`
- else if groups contains `ai-assist-recite-user` -> `recite_user`
- else -> `guest`

## 10) Security Gotchas (Do Not Skip)

Most important rule:

- Never trust auth headers coming directly from the internet.
- Only trust headers injected by your reverse proxy.

Also do:

- HTTPS everywhere
- secure cookies
- rate limiting
- audit logs for privileged actions
- explicit source allowlists for guest mode

## 11) What Changes in This Project

Minimum implementation targets:

1. Add role extraction helper in backend.
2. Add endpoint-level permission checks.
3. Add retrieval source scoping by role.
4. Add KB suggestion workflow for `recite_user`.
5. Add admin approve/reject/publish workflow.

## 12) Implementation Order (Recommended)

Phase 1:
- Role parsing + permission checks in app
- Guest KB-only source restriction

Phase 2:
- Put app behind oauth2-proxy + Authentik
- Validate group-based roles

Phase 3:
- KB pending queue + admin moderation

Phase 4:
- hardening + observability

## 13) “Explain Like I’m Busy”

If time is tight:

1. Keep current app.
2. Put oauth2-proxy + Authentik in front.
3. Map Authentik groups to app roles.
4. Enforce guest = KB-only.
5. Add pending KB suggestions for recite users.
6. Admin approves publish.

That gets you secure enough fast, without a full rewrite.
