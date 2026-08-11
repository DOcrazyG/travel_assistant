"""Local-account registration, login, refresh, logout, and bearer verification."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings
from app.core.errors import APIError
from app.core.rate_limit import RateLimiter
from app.core.security import (
    decode_access_token,
    hash_identifier,
    hash_password,
    hash_refresh_token,
    identifier_key,
    issue_access_token,
    new_refresh_token,
    verify_password,
)
from app.models.auth import AuthSession, RefreshToken, RevokedAccessToken
from app.models.base import utc_now
from app.models.operations import SecurityAuditEvent
from app.models.users import User
from app.schemas.users import UserCreate

_DUMMY_PASSWORD_HASH = hash_password("not-a-real-user-password")


def _column(model: type[SQLModel], name: str) -> Any:
    """Read a mapped column without losing SQLModel's runtime mapping metadata."""

    return inspect(model).columns[name]


async def ensure_bootstrap_admin(session: AsyncSession, settings: Settings) -> None:
    """Create the one configured administrator when no administrator exists yet."""

    result = await session.exec(
        select(User).where(
            _column(User, "is_admin").is_(True),
            _column(User, "deleted_at").is_(None),
        )
    )
    if result.one_or_none() is not None:
        return
    if settings.bootstrap_admin_email is None or settings.bootstrap_admin_password is None:
        raise RuntimeError(
            "No administrator exists; BOOTSTRAP_ADMIN_EMAIL and "
            "BOOTSTRAP_ADMIN_PASSWORD are required"
        )

    payload = UserCreate(
        email=settings.bootstrap_admin_email,
        password=settings.bootstrap_admin_password,
    )
    administrator = User(
        email=payload.email,
        email_normalized=payload.email,
        password_hash=hash_password(payload.password.get_secret_value()),
        status="active",
        is_admin=True,
    )
    session.add(administrator)
    # SQLAlchemy does not know the ordering from scalar UUID foreign keys alone.
    # Persist the parent before adding the audit child that references it.
    await session.flush()
    session.add(
        SecurityAuditEvent(
            user_id=administrator.id,
            event_type="auth.bootstrap_admin",
            outcome="success",
            details={"source": "startup"},
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        result = await session.exec(
            select(User).where(
                _column(User, "is_admin").is_(True),
                _column(User, "deleted_at").is_(None),
            )
        )
        if result.one_or_none() is None:
            raise


@dataclass(frozen=True)
class AuthRequestContext:
    """Only the request metadata that the domain service may persist."""

    request_id: UUID | None
    ip_address: str | None
    user_agent: str | None


@dataclass(frozen=True)
class AuthTokens:
    """Credentials issued from successful password or refresh authentication."""

    access_token: str
    access_expires_at: datetime
    refresh_token: str
    user: User


class AuthService:
    """Authentication operations with transaction ownership and audit records."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        rate_limiter: RateLimiter,
    ) -> None:
        self.session = session
        self.settings = settings
        self.rate_limiter = rate_limiter

    async def register(self, payload: UserCreate, context: AuthRequestContext) -> User:
        """Create an active local account without logging it in."""

        await self._check_rate_limit(
            f"register:ip:{identifier_key(context.ip_address, self.settings)}",
            limit=5,
            window_seconds=3600,
            context=context,
            operation="register",
        )
        email = payload.email
        existing = await self._find_user_by_email(email)
        if existing is not None:
            await self._audit(
                context,
                None,
                "auth.register",
                "denied",
                {"reason": "email_unavailable"},
            )
            await self.session.commit()
            raise APIError(409, "email_unavailable", "This email cannot be registered.")

        user = User(
            email=email,
            email_normalized=email,
            password_hash=hash_password(payload.password.get_secret_value()),
            status="active",
        )
        self.session.add(user)
        await self.session.flush()
        await self._audit(context, user.id, "auth.register", "success", {})
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise APIError(409, "email_unavailable", "This email cannot be registered.") from error
        await self.session.refresh(user)
        return user

    async def login(
        self,
        *,
        email: str,
        password: str,
        context: AuthRequestContext,
    ) -> AuthTokens:
        """Verify credentials, enforce session limits, and issue a token pair."""

        await self._check_rate_limit(
            f"login:ip:{identifier_key(context.ip_address, self.settings)}",
            limit=10,
            window_seconds=15 * 60,
            context=context,
            operation="login",
        )
        await self._check_rate_limit(
            f"login:email:{identifier_key(email, self.settings)}",
            limit=10,
            window_seconds=15 * 60,
            context=context,
            operation="login",
        )
        user = await self._find_user_by_email(email)
        password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
        password_valid, upgraded_hash = verify_password(password, password_hash)
        if user is None or user.status != "active" or not password_valid:
            await self._audit(context, user.id if user else None, "auth.login", "failure", {})
            await self.session.commit()
            raise APIError(401, "invalid_credentials", "Email or password is incorrect.")

        if upgraded_hash is not None:
            user.password_hash = upgraded_hash
        user.last_login_at = utc_now()
        tokens = await self._create_session_tokens(user, context)
        await self._audit(context, user.id, "auth.login", "success", {})
        await self.session.commit()
        return tokens

    async def refresh(self, refresh_token: str, context: AuthRequestContext) -> AuthTokens:
        """Consume a refresh token once and replace it in the same session family."""

        token_hash = hash_refresh_token(refresh_token)
        result = await self.session.exec(
            select(RefreshToken)
            .where(_column(RefreshToken, "token_hash") == token_hash)
            .with_for_update()
        )
        stored_token = result.one_or_none()
        if stored_token is None:
            await self._audit(context, None, "auth.refresh", "failure", {"reason": "unknown_token"})
            await self.session.commit()
            raise APIError(401, "invalid_refresh_token", "Refresh authentication is invalid.")

        session = await self.session.get(AuthSession, stored_token.session_id, with_for_update=True)
        user = await self.session.get(User, session.user_id) if session else None
        now = utc_now()
        if stored_token.consumed_at is not None or stored_token.revoked_at is not None:
            if session and session.revoked_at is None:
                session.revoked_at = now
                session.revoked_reason = "refresh_token_reuse"
            await self._audit(
                context,
                user.id if user else None,
                "auth.refresh_reuse",
                "denied",
                {},
            )
            await self.session.commit()
            raise APIError(401, "invalid_refresh_token", "Refresh authentication is invalid.")
        if (
            session is None
            or user is None
            or user.status != "active"
            or session.revoked_at is not None
            or stored_token.expires_at <= now
            or session.expires_at <= now
        ):
            await self._audit(
                context,
                user.id if user else None,
                "auth.refresh",
                "failure",
                {"reason": "expired_or_revoked"},
            )
            await self.session.commit()
            raise APIError(401, "invalid_refresh_token", "Refresh authentication is invalid.")

        await self._check_rate_limit(
            f"refresh:session:{session.id}",
            limit=30,
            window_seconds=15 * 60,
            context=context,
            operation="refresh",
            user_id=user.id,
        )
        stored_token.consumed_at = now
        session.last_used_at = now
        raw_token = new_refresh_token()
        new_token = RefreshToken(
            session_id=session.id,
            token_hash=hash_refresh_token(raw_token),
            expires_at=session.expires_at,
        )
        self.session.add(new_token)
        await self.session.flush()
        stored_token.replaced_by_id = new_token.id
        access_token, _, access_expires_at = issue_access_token(user.id, self.settings)
        await self._audit(context, user.id, "auth.refresh", "success", {})
        await self.session.commit()
        return AuthTokens(access_token, access_expires_at, raw_token, user)

    async def logout(
        self,
        refresh_token: str | None,
        access_token: str | None,
        context: AuthRequestContext,
    ) -> None:
        """Revoke the current refresh session and supplied short-lived access JWT."""

        user_id: UUID | None = None
        if refresh_token:
            result = await self.session.exec(
                select(RefreshToken).where(
                    _column(RefreshToken, "token_hash") == hash_refresh_token(refresh_token)
                )
            )
            stored_token = result.one_or_none()
            if stored_token:
                session = await self.session.get(AuthSession, stored_token.session_id)
                if session and session.revoked_at is None:
                    session.revoked_at = utc_now()
                    session.revoked_reason = "logout"
                    user_id = session.user_id
        if access_token:
            try:
                token_user_id, token_id, expires_at = decode_access_token(
                    access_token, self.settings
                )
            except APIError:
                pass
            else:
                user_id = user_id or token_user_id
                if await self.session.get(RevokedAccessToken, token_id) is None:
                    self.session.add(
                        RevokedAccessToken(
                            jti=token_id,
                            user_id=token_user_id,
                            expires_at=expires_at,
                            reason="logout",
                        )
                    )
        await self._audit(context, user_id, "auth.logout", "success", {})
        await self.session.commit()

    async def current_user(self, access_token: str) -> User:
        """Resolve an access token to an active, non-revoked local account."""

        user_id, token_id, _ = decode_access_token(access_token, self.settings)
        if await self.session.get(RevokedAccessToken, token_id) is not None:
            raise APIError(401, "invalid_access_token", "Authentication credentials are invalid.")
        user = await self.session.get(User, user_id)
        if user is None or user.status != "active" or user.deleted_at is not None:
            raise APIError(401, "invalid_access_token", "Authentication credentials are invalid.")
        return user

    async def _create_session_tokens(self, user: User, context: AuthRequestContext) -> AuthTokens:
        now = utc_now()
        active_sessions = await self._active_sessions_for_user(user.id)
        excess_sessions = len(active_sessions) - self.settings.max_active_auth_sessions + 1
        for old_session in active_sessions[: max(0, excess_sessions)]:
            old_session.revoked_at = now
            old_session.revoked_reason = "session_limit"

        auth_session = AuthSession(
            user_id=user.id,
            expires_at=now + timedelta(days=self.settings.refresh_session_days),
            user_agent=context.user_agent,
            ip_hash=hash_identifier(context.ip_address, self.settings),
        )
        self.session.add(auth_session)
        await self.session.flush()
        raw_refresh_token = new_refresh_token()
        refresh_token = RefreshToken(
            session_id=auth_session.id,
            token_hash=hash_refresh_token(raw_refresh_token),
            expires_at=auth_session.expires_at,
        )
        self.session.add(refresh_token)
        access_token, _, access_expires_at = issue_access_token(user.id, self.settings)
        return AuthTokens(access_token, access_expires_at, raw_refresh_token, user)

    async def _find_user_by_email(self, email: str) -> User | None:
        result = await self.session.exec(
            select(User).where(
                _column(User, "email_normalized") == email,
                _column(User, "deleted_at").is_(None),
            )
        )
        return result.one_or_none()

    async def _active_sessions_for_user(self, user_id: UUID) -> list[AuthSession]:
        result = await self.session.exec(
            select(AuthSession)
            .where(
                _column(AuthSession, "user_id") == user_id,
                _column(AuthSession, "revoked_at").is_(None),
            )
            .order_by(_column(AuthSession, "created_at"))
        )
        return list(result.all())

    async def _audit(
        self,
        context: AuthRequestContext,
        user_id: UUID | None,
        event_type: str,
        outcome: str,
        details: dict[str, str],
    ) -> None:
        self.session.add(
            SecurityAuditEvent(
                user_id=user_id,
                event_type=event_type,
                outcome=outcome,
                request_id=context.request_id,
                ip_hash=hash_identifier(context.ip_address, self.settings),
                user_agent=context.user_agent,
                details=details,
            )
        )

    async def _check_rate_limit(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
        context: AuthRequestContext,
        operation: str,
        user_id: UUID | None = None,
    ) -> None:
        """Apply a limit and persist the rejection without storing sensitive keys."""

        try:
            await self.rate_limiter.check(key, limit=limit, window_seconds=window_seconds)
        except APIError as error:
            await self._audit(
                context,
                user_id,
                "auth.rate_limit",
                "denied",
                {"operation": operation},
            )
            await self.session.commit()
            raise error
