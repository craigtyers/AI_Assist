from __future__ import annotations

from typing import Protocol

from auth.types import Principal


class AuthProvider(Protocol):
    mode: str

    def get_principal(self, handler) -> Principal: ...
