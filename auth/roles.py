from __future__ import annotations

ROLE_PUBLIC = "visitor"
ROLE_RECITE = "user"
ROLE_ADMIN = "admin"

ROLE_LEVELS = {
    ROLE_PUBLIC: 1,
    ROLE_RECITE: 2,
    ROLE_ADMIN: 3,
}

DEFAULT_ROLE = ROLE_PUBLIC

def normalize_role(value: str | None) -> str:
    role = (value or "").strip().lower()
    if role in ROLE_LEVELS:
        return role
    return DEFAULT_ROLE
