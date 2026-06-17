# Next Steps: Public + Internal AI Assistant with Role-Based Access

## 1) Goal (What We Want)

Build a deployable version of this assistant for a public server with three access levels:

1. `guest` (no auth):
- Public users can ask questions.
- Strictly limited to safe/public knowledge sources (primarily `KnowledgeBase`).
- Additional output guardrails to avoid leaking internal details.

2. `recite_user` (authenticated):
- Recognized internal Recite users.
- Full repo-backed RAG access.
- Can suggest publishing an answer as a KB article.
- Cannot directly publish.

3. `admin` (authenticated):
- Full internal access.
- Can create/publish KB articles.
- Can review and approve/reject suggested KB articles.
- Full moderation and admin capabilities.

## 2) Why This Matters

- `Security`: Prevent accidental exposure of private code/secrets.
- `Usability`: Public users still get helpful answers from curated KB docs.
- `Quality`: Internal users can improve KB over time via suggestions.
- `Control`: Admin approval loop keeps published KB accurate and intentional.
- `Scalability`: Clear RBAC avoids one-size-fits-all behavior.

## 3) Recommended Architecture (Pragmatic Path)

## Keep current Python app; add authz and policy enforcement

Do **not** rewrite to Laravel or Node immediately.  
Most risk sits in retrieval and authorization, not framework choice.

Recommended stack:
- Current `app.py` + `rag/*` remains core app.
- Add OIDC auth layer in front via Authentik (Google SSO behind it).
- Use reverse proxy + auth proxy pattern (`oauth2-proxy` or Authentik forward-auth).
- App receives trusted identity/role headers and enforces RBAC server-side.

## Why this path
- Lowest migration risk and fastest delivery.
- Preserves all current RAG/KB work.
- Focuses on true risk areas: source scoping, endpoint permissions, moderation workflow.

## 4) Authentication and SSO

Use Authentik as identity provider:
- Google configured as upstream IdP in Authentik.
- Authentik groups map to app roles (`recite_user`, `admin`).

Deployment pattern:
- Internet -> Reverse Proxy -> Auth layer -> `app.py`.
- Public endpoints can allow anonymous.
- Internal/admin routes require OIDC auth.

Trusted headers (example, from proxy):
- `X-Auth-Request-User`
- `X-Auth-Request-Email`
- `X-Auth-Request-Groups`

App derives role from groups:
- group contains `ai-assist-admin` -> `admin`
- group contains `ai-assist-recite-user` -> `recite_user`
- otherwise `guest`

## 5) Authorization Model (RBAC)

Enforce in backend, not only in UI.

Permission matrix:

- `guest`
  - `/api/chat`: yes (restricted sources)
  - `/api/search`: yes (restricted sources)
  - `/api/kb/check`: no
  - `/api/kb/create`: no
  - `/api/kb/create-form`: no
  - `/api/index`: no
  - admin moderation endpoints: no

- `recite_user`
  - `/api/chat`: yes (full sources)
  - `/api/search`: yes (full sources)
  - `/api/kb/suggest`: yes (create pending KB)
  - `/api/kb/create`: no direct publish
  - `/api/index`: maybe yes (or admin-only, preferred)
  - moderation endpoints: no

- `admin`
  - all above plus:
  - publish KB (`/api/kb/create` or `/api/kb/publish`)
  - approve/reject suggestions
  - reindex control

## 6) Source Scoping by Role (Most Important Control)

This is the core anti-leak mechanism.

Policy:
- `guest`:
  - allow only `KnowledgeBase` repo (and optional explicit public docs folder).
  - deny all code repos from retrieval candidates.
- `recite_user` and `admin`:
  - allow full configured repos.

Implementation:
- Extend `search_chunks(..., role=...)`.
- Apply SQL-level source filters before ranking.
- Keep policy in one central function to avoid endpoint drift.

## 7) Guardrails Strategy (Defense-in-Depth)

Prompt guardrails alone are not enough.

Use layered controls:

1. Retrieval guardrails (primary):
- role-based source allowlist
- path denylist for sensitive files (e.g. secrets/config keys)

2. Output guardrails (secondary):
- post-generation checks for known sensitive patterns
- fallback response when risky output detected

3. Operational guardrails:
- rate limits
- max token/output limits
- audit logs

## 8) KB Suggestion and Approval Workflow

Current publish flow is direct. Add moderation pipeline:

Folders:
- `KnowledgeBase/` = published
- `KnowledgeBase_pending/` = suggested, not public

Proposed flow:
- `recite_user` clicks "Suggest KB article"
- server writes pending article + metadata (author, timestamp, source refs)
- admin reviews pending items
- admin approves -> move to `KnowledgeBase/`, update index
- admin rejects -> mark rejected with reason

Metadata example:
- suggestion id
- question
- answer body
- suggested by (email/user id)
- source refs
- status (`pending|approved|rejected`)
- reviewer and decision timestamp

## 9) Public vs Internal Surface

Recommended:

- `assist-public.reciteme.com`
  - anonymous allowed
  - guest role behavior only
  - no admin/internal controls in UI

- `assist-internal.reciteme.com`
  - SSO required
  - `recite_user` and `admin` features

Can be same app with role-aware rendering; split hostnames reduces accidental exposure.

## 10) API/Code Changes Needed

Backend:
- add role extraction middleware/helper
- add per-endpoint permission checks
- add `role` to retrieval/search functions
- add pending KB endpoints:
  - `POST /api/kb/suggest`
  - `GET /api/kb/pending`
  - `POST /api/kb/pending/{id}/approve`
  - `POST /api/kb/pending/{id}/reject`

Frontend:
- hide/show controls by role
- public UI should not display privileged actions
- internal UI should support suggestion queue (admin panel)

Config:
- role/group mapping config
- trusted proxy config (only trust auth headers from proxy)

## 11) Security Requirements Checklist

- enforce HTTPS only
- secure headers (HSTS, CSP, X-Frame-Options, etc.)
- trusted reverse proxy chain configured
- do not trust auth headers directly from internet
- endpoint-level authz checks
- source-level retrieval restrictions
- audit logging enabled
- rotate and secure any secrets/tokens

## 12) Observability and Audit

Log:
- user, role, endpoint, query hash, latency, status
- KB suggestion + moderation events
- denied access attempts

Metrics:
- request volume by role
- answer latency
- retrieval source mix
- moderation throughput

## 13) Rollout Plan (Phased)

Phase 1: Foundation
- Add role extraction + endpoint permissions.
- Add role-based source scoping.
- Keep current UI mostly intact.

Phase 2: Auth integration
- Put app behind Authentik/OIDC proxy.
- Map groups to roles.
- Verify anonymous/public path behavior.

Phase 3: KB moderation
- Implement `KnowledgeBase_pending`.
- Add suggestion and approve/reject flow.

Phase 4: Hardening
- Add rate limiting, audit dashboards, output safety filters.
- Pen-test-style leak testing with synthetic secret prompts.

## 14) Success Criteria

- Guest can never retrieve internal repo content.
- Recite users can query internal code but cannot publish KB directly.
- Admin can approve/reject suggestions and publish.
- Authenticated roles are derived from SSO groups reliably.
- No breaking regressions in current RAG and KB workflow.

## 15) Optional Future Enhancements

- Model routing by role (lighter public model, stronger internal model).
- Per-tenant KB partitions.
- Approval SLAs and notification workflow.
- Semantic deduplication for KB suggestions.

---

This plan keeps current momentum, avoids risky rewrites, and targets the real risk boundary: retrieval + authorization.
