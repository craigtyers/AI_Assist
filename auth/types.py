from __future__ import annotations

from dataclasses import dataclass

from auth.roles import ROLE_LEVELS


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str | None
    role: str
    is_authenticated: bool

    @property
    def role_level(self) -> int:
        return ROLE_LEVELS.get(self.role, 1)
