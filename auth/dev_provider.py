from __future__ import annotations

import os
import secrets
from typing import Dict

from auth.roles import DEFAULT_ROLE, ROLE_LEVELS, normalize_role
from auth.types import Principal


class DevAuthProvider:
    mode = "dev"

    def __init__(self) -> None:
        self._session_cookie_name = os.getenv("DEV_SESSION_COOKIE_NAME", "nbert_session")
        self._session_roles: Dict[str, str] = {}

    @property
    def session_cookie_name(self) -> str:
        return self._session_cookie_name

    @staticmethod
    def _parse_cookies(raw_cookie: str) -> dict[str, str]:
        cookies: dict[str, str] = {}
        for item in raw_cookie.split(";"):
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            key = key.strip()
            if not key:
                continue
            cookies[key] = value.strip()
        return cookies

    def _session_id_from_handler(self, handler) -> str:
        cookies = self._parse_cookies(handler.headers.get("Cookie", ""))
        return cookies.get(self._session_cookie_name, "")

    def get_principal(self, handler) -> Principal:
        sid = self._session_id_from_handler(handler)
        role = normalize_role(self._session_roles.get(sid, DEFAULT_ROLE))
        return Principal(user_id=f"dev:{sid or 'anonymous'}", email=None, role=role, is_authenticated=False)

    def set_role_cookie(self, handler, role: str) -> None:
        role_norm = normalize_role(role)
        if role_norm not in ROLE_LEVELS:
            raise ValueError(f"Invalid role: {role}")
        sid = self._session_id_from_handler(handler)
        if not sid:
            sid = secrets.token_hex(16)
        self._session_roles[sid] = role_norm
        handler.send_header("Set-Cookie", f"{self._session_cookie_name}={sid}; Path=/; HttpOnly; SameSite=Lax")
