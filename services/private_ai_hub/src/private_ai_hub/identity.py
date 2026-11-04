from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Permission(StrEnum):
    CHAT_USE = "chat.use"
    AGENT_USE = "agent.use"
    ADMIN_MANAGE = "admin.manage"
    USER_MANAGE = "user.manage"
    POLICY_READ = "policy.read"
    POLICY_WRITE = "policy.write"
    PROJECT_MANAGE = "project.manage"
    SECURITY_AUDIT_READ = "audit.security.read"
    CONVERSATION_AUDIT_READ = "audit.conversation.read"


BUILTIN_ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "user": frozenset(
        {
            Permission.CHAT_USE,
        }
    ),
    "admin": frozenset(
        {
            Permission.CHAT_USE,
            Permission.ADMIN_MANAGE,
            Permission.USER_MANAGE,
            Permission.POLICY_READ,
            Permission.POLICY_WRITE,
            Permission.PROJECT_MANAGE,
            Permission.SECURITY_AUDIT_READ,
        }
    ),
    "compliance-auditor": frozenset(
        {
            Permission.CONVERSATION_AUDIT_READ,
        }
    ),
}


@dataclass(frozen=True)
class Organization:
    id: str
    name: str


@dataclass(frozen=True)
class User:
    id: str
    organization_id: str
    username: str
    display_name: str
    enabled: bool


@dataclass(frozen=True)
class Group:
    id: str
    organization_id: str
    name: str


@dataclass(frozen=True)
class Role:
    id: str
    organization_id: str
    name: str
    built_in: bool


@dataclass(frozen=True)
class Principal:
    user: User
    permissions: frozenset[str]

    def has_permission(self, permission: Permission | str) -> bool:
        return str(permission) in self.permissions


class AuthorizationError(PermissionError):
    """Raised when an authenticated principal lacks a required permission."""


def require_permission(
    principal: Principal,
    permission: Permission | str,
) -> None:
    required = str(permission)
    if required not in principal.permissions:
        raise AuthorizationError(f"permission required: {required}")
