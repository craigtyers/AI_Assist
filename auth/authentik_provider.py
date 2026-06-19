from __future__ import annotations

import os
from typing import Iterable

from auth.roles import DEFAULT_ROLE, ROLE_ADMIN, ROLE_RECITE
from auth.types import Principal


class AuthentikAuthProvider:
    mode = "authentik"

    def __init__(self) -> None:
        try:
            import jwt
            from jwt import PyJWKClient
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "AUTH_MODE=authentik requires PyJWT. Install with: pip install PyJWT"
            ) from exc

        self._jwt = jwt
        self._jwks_client_cls = PyJWKClient

        self._issuer = os.getenv("OIDC_ISSUER", "").strip()
        self._audience = os.getenv("OIDC_AUDIENCE", "").strip()
        self._jwks_url = os.getenv("OIDC_JWKS_URL", "").strip()
        self._algorithms = [a.strip() for a in os.getenv("OIDC_ALGORITHMS", "RS256").split(",") if a.strip()]
        self._role_claim = os.getenv("AUTH_ROLE_CLAIM", "groups").strip() or "groups"
        self._token_cookie_name = os.getenv("AUTH_ACCESS_TOKEN_COOKIE", "access_token").strip() or "access_token"

        self._level3_groups = self._csv_env("AUTH_ROLE_MAP_LEVEL3", ["recite-admins"])
        self._level2_groups = self._csv_env("AUTH_ROLE_MAP_LEVEL2", ["recite-users"])

        if not self._issuer:
            raise RuntimeError("OIDC_ISSUER is required when AUTH_MODE=authentik")
        if not self._audience:
            raise RuntimeError("OIDC_AUDIENCE is required when AUTH_MODE=authentik")
        if not self._jwks_url:
            raise RuntimeError("OIDC_JWKS_URL is required when AUTH_MODE=authentik")

        self._jwk_client = self._jwks_client_cls(self._jwks_url)

    @staticmethod
    def _csv_env(name: str, default: list[str]) -> set[str]:
        raw = os.getenv(name, ",".join(default)).strip()
        if not raw:
            return set(default)
        return {part.strip() for part in raw.split(",") if part.strip()}

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

    def _extract_bearer(self, handler) -> str:
        authz = (handler.headers.get("Authorization", "") or "").strip()
        if authz.lower().startswith("bearer "):
            return authz[7:].strip()
        cookies = self._parse_cookies(handler.headers.get("Cookie", ""))
        return cookies.get(self._token_cookie_name, "").strip()

    @staticmethod
    def _normalize_groups(value: object) -> set[str]:
        if value is None:
            return set()
        if isinstance(value, str):
            return {value}
        if isinstance(value, Iterable):
            out: set[str] = set()
            for v in value:
                if isinstance(v, str) and v.strip():
                    out.add(v.strip())
            return out
        return set()

    def _role_from_claims(self, claims: dict) -> str:
        groups = self._normalize_groups(claims.get(self._role_claim))
        if groups & self._level3_groups:
            return ROLE_ADMIN
        if groups & self._level2_groups:
            return ROLE_RECITE
        return DEFAULT_ROLE

    def get_principal(self, handler) -> Principal:
        token = self._extract_bearer(handler)
        if not token:
            return Principal(user_id="anonymous", email=None, role=DEFAULT_ROLE, is_authenticated=False)

        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(token)
            claims = self._jwt.decode(
                token,
                signing_key.key,
                algorithms=self._algorithms,
                audience=self._audience,
                issuer=self._issuer,
            )
        except Exception:  # noqa: BLE001
            return Principal(user_id="anonymous", email=None, role=DEFAULT_ROLE, is_authenticated=False)

        role = self._role_from_claims(claims)
        user_id = str(claims.get("sub") or "anonymous")
        email = claims.get("email")
        email_str = str(email) if isinstance(email, str) and email.strip() else None
        return Principal(user_id=user_id, email=email_str, role=role, is_authenticated=True)
