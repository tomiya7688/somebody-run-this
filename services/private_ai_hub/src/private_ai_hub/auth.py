from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import logging
from pathlib import Path
import secrets
import time
from typing import Mapping, Protocol

from .identity import Principal, User
from .identity_store import IdentityStore


LOCAL_PROVIDER_ID = "local"

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_DUMMY_SALT = b"private-ai-local-auth-dummy-salt-v1"

logger = logging.getLogger(__name__)


class AuthenticationError(PermissionError):
    """Raised when credentials or a session cannot be authenticated."""


class AuthProvider(Protocol):
    provider_id: str

    def authenticate(
        self,
        organization_id: str,
        identifier: str,
        secret: str,
    ) -> User | None:
        """Authenticate provider credentials and return a domain User."""


@dataclass(frozen=True)
class SessionToken:
    value: str
    expires_at: int


@dataclass(frozen=True)
class LoginResult:
    principal: Principal
    session: SessionToken


def _password_bytes(password: object) -> bytes:
    if not isinstance(password, str):
        raise ValueError("password must be a string")
    encoded = password.encode("utf-8")
    if len(encoded) < 12:
        raise ValueError("password must be at least 12 UTF-8 bytes")
    if len(encoded) > 1024:
        raise ValueError("password is too long")
    return encoded


def _derive_password_hash(
    password_bytes: bytes,
    *,
    salt: bytes,
    n: int,
    r: int,
    p: int,
    dklen: int,
) -> bytes:
    return hashlib.scrypt(
        password_bytes,
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=dklen,
    )


def _session_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _safe_scrypt_parameters(n: object, r: object, p: object, dklen: object) -> bool:
    values = (n, r, p, dklen)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        return False
    if n < 2**12 or n > 2**18 or n & (n - 1):
        return False
    if not 1 <= r <= 32:
        return False
    if not 1 <= p <= 8:
        return False
    if not 16 <= dklen <= 64:
        return False
    return True


class LocalAuthProvider:
    provider_id = LOCAL_PROVIDER_ID

    def __init__(self, store: IdentityStore) -> None:
        self.store = store

    def set_password(self, user_id: str, password: str) -> None:
        encoded = _password_bytes(password)
        salt = secrets.token_bytes(16)
        password_hash = _derive_password_hash(
            encoded,
            salt=salt,
            n=_SCRYPT_N,
            r=_SCRYPT_R,
            p=_SCRYPT_P,
            dklen=_SCRYPT_DKLEN,
        )
        self.store.set_local_credential(
            user_id,
            salt=salt,
            password_hash=password_hash,
            scrypt_n=_SCRYPT_N,
            scrypt_r=_SCRYPT_R,
            scrypt_p=_SCRYPT_P,
            dklen=_SCRYPT_DKLEN,
        )

    def authenticate(
        self,
        organization_id: str,
        identifier: str,
        secret: str,
    ) -> User | None:
        try:
            encoded = _password_bytes(secret)
        except ValueError:
            # Authentication must not expose password-policy details.
            return None

        user = self.store.find_user_by_username(
            organization_id,
            identifier,
        )
        credential = (
            self.store.get_local_credential(user.id)
            if user is not None
            else None
        )

        if credential is None:
            _derive_password_hash(
                encoded,
                salt=_DUMMY_SALT,
                n=_SCRYPT_N,
                r=_SCRYPT_R,
                p=_SCRYPT_P,
                dklen=_SCRYPT_DKLEN,
            )
            return None

        salt, expected_hash, n, r, p, dklen = credential
        if not _safe_scrypt_parameters(n, r, p, dklen):
            logger.warning("invalid local credential parameters for user %s", user.id)
            return None

        actual_hash = _derive_password_hash(
            encoded,
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=dklen,
        )
        if not hmac.compare_digest(actual_hash, expected_hash):
            return None
        if user is None or not user.enabled:
            return None
        return user


def _principal_for_user(store: IdentityStore, user: User) -> Principal:
    return Principal(
        user=user,
        permissions=store.permissions_for_user(user.id),
        group_ids=store.group_ids_for_user(user.id),
        role_ids=store.role_ids_for_user(user.id),
    )


class SessionManager:
    def __init__(
        self,
        store: IdentityStore,
        *,
        ttl_seconds: int = 12 * 60 * 60,
    ) -> None:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
            raise ValueError("session ttl must be an integer")
        if not 300 <= ttl_seconds <= 31 * 24 * 60 * 60:
            raise ValueError(
                "session ttl must be between 300 seconds and 31 days"
            )
        self.store = store
        self.ttl_seconds = ttl_seconds

    def issue(self, user: User, *, provider_id: str) -> SessionToken:
        now = int(time.time())
        expires_at = now + self.ttl_seconds
        token = secrets.token_urlsafe(32)
        self.store.create_session_record(
            token_hash=_session_hash(token),
            user_id=user.id,
            provider_id=provider_id,
            created_at=now,
            expires_at=expires_at,
        )
        return SessionToken(value=token, expires_at=expires_at)

    def authenticate(self, token: object) -> Principal | None:
        if not isinstance(token, str):
            return None
        if not 20 <= len(token) <= 4096:
            return None

        user_id = self.store.active_session_user_id(
            _session_hash(token),
            now=int(time.time()),
        )
        if user_id is None:
            return None

        user = self.store.get_user(user_id)
        if user is None or not user.enabled:
            return None

        return _principal_for_user(self.store, user)

    def revoke(self, token: object) -> None:
        if not isinstance(token, str) or not token:
            return
        self.store.revoke_session(
            _session_hash(token),
            now=int(time.time()),
        )

    def revoke_all(self, user_id: str) -> None:
        self.store.revoke_all_sessions(
            user_id,
            now=int(time.time()),
        )


class AuthService:
    def __init__(
        self,
        store: IdentityStore,
        providers: Mapping[str, AuthProvider],
        *,
        session_ttl_seconds: int = 12 * 60 * 60,
    ) -> None:
        normalized: dict[str, AuthProvider] = {}
        for provider_id, provider in providers.items():
            if not isinstance(provider_id, str) or not provider_id.strip():
                raise ValueError("provider id must be a non-empty string")
            key = provider_id.strip().casefold()
            if provider.provider_id.casefold() != key:
                raise ValueError("provider registry key does not match provider id")
            normalized[key] = provider
        if not normalized:
            raise ValueError("at least one auth provider is required")

        self.store = store
        self.providers = normalized
        self.sessions = SessionManager(
            store,
            ttl_seconds=session_ttl_seconds,
        )

    def login(
        self,
        *,
        organization_id: str,
        provider_id: str,
        identifier: str,
        secret: str,
    ) -> LoginResult:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (organization_id, provider_id, identifier, secret)
        ):
            raise AuthenticationError("authentication failed")

        provider = self.providers.get(provider_id.strip().casefold())
        if provider is None:
            raise AuthenticationError("authentication failed")

        user = provider.authenticate(
            organization_id,
            identifier,
            secret,
        )
        if user is None or not user.enabled:
            raise AuthenticationError("authentication failed")

        session = self.sessions.issue(
            user,
            provider_id=provider.provider_id,
        )
        principal = _principal_for_user(self.store, user)
        return LoginResult(principal=principal, session=session)

    def authenticate_session(self, token: object) -> Principal | None:
        return self.sessions.authenticate(token)

    def logout(self, token: object) -> None:
        self.sessions.revoke(token)

    def logout_all(self, principal: Principal) -> None:
        self.sessions.revoke_all(principal.user.id)


def build_local_auth_service(
    database_path: Path | str,
    *,
    session_ttl_seconds: int = 12 * 60 * 60,
) -> tuple[AuthService, LocalAuthProvider]:
    store = IdentityStore(database_path)
    provider = LocalAuthProvider(store)
    service = AuthService(
        store,
        {provider.provider_id: provider},
        session_ttl_seconds=session_ttl_seconds,
    )
    return service, provider


def bootstrap_local_admin(
    database_path: Path | str,
    *,
    organization_id: str,
    organization_name: str,
    username: str,
    display_name: str | None,
    password: str,
) -> User:
    store = IdentityStore(database_path)

    organization = store.get_organization(organization_id)
    if organization is None:
        store.create_organization(organization_id, organization_name)

    if store.find_user_by_username(organization_id, username) is not None:
        raise ValueError("a user with that username already exists")

    user = store.create_user(
        organization_id,
        username,
        display_name=display_name,
    )
    provider = LocalAuthProvider(store)
    provider.set_password(user.id, password)

    roles = store.ensure_builtin_roles(organization_id)
    store.assign_role_to_user(user.id, roles["admin"].id)
    return user
