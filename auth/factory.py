from __future__ import annotations

import os

from auth.authentik_provider import AuthentikAuthProvider
from auth.dev_provider import DevAuthProvider
from auth.provider import AuthProvider


def create_auth_provider() -> AuthProvider:
    mode = os.getenv("AUTH_MODE", "dev").strip().lower() or "dev"
    if mode == "dev":
        return DevAuthProvider()
    if mode == "authentik":
        return AuthentikAuthProvider()
    raise RuntimeError(f"Unsupported AUTH_MODE: {mode}. Expected 'dev' or 'authentik'.")
