# SPDX-License-Identifier: Apache-2.0

"""OIDC SSO endpoints. Login redirect -> IdP -> callback -> provision ->
Raggie tokens. SAML reuses the same identity resolution via its own ACS handler.

The flow is bound to the browser that started it: /login stores the random
state, the nonce and the PKCE verifier in a short-lived, signed, HttpOnly
cookie, and /callback only proceeds when the returned state matches that cookie
(login CSRF / code injection) and the ID token carries the nonce (replay).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from raggie_control_plane.api.deps import get_conn
from raggie_control_plane.auth.oidc import OIDCClient
from raggie_control_plane.auth.service import AuthService, SSOLinkError
from raggie_control_plane.config import settings
from raggie_control_plane.db.repositories import AuditRepo, OrganizationRepo

router = APIRouter(prefix="/api/v1/auth/sso", tags=["sso"])

log = logging.getLogger("control-plane.sso")

_FLOW_AUD = "sso-flow"
_FLOW_COOKIE = "raggie_sso_flow"


def get_oidc() -> OIDCClient:
    return OIDCClient()


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _cookie_secure() -> bool:
    # The cookie must come back on the IdP redirect, so it follows the scheme of
    # the registered callback URL (plain-http only for local development).
    return settings.oidc_redirect_url.lower().startswith("https://")


def _sign_flow(state: str, nonce: str, verifier: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "aud": _FLOW_AUD,
            "state": state,
            "nonce": nonce,
            "cv": verifier,
            "iat": now,
            "exp": now + timedelta(seconds=settings.sso_state_ttl_seconds),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def _verify_flow(cookie: str | None, state: str) -> dict[str, Any] | None:
    if not cookie:
        return None
    try:
        flow = jwt.decode(cookie, settings.jwt_secret, algorithms=["HS256"], audience=_FLOW_AUD)
    except jwt.PyJWTError:
        return None
    if not hmac.compare_digest(str(flow.get("state", "")).encode(), state.encode()):
        return None
    return flow


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str


@router.get("/login")
async def sso_login(oidc: OIDCClient = Depends(get_oidc)) -> RedirectResponse:
    if not oidc.enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sso is not configured")
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)  # 86 chars, within RFC 7636's 43..128
    response = RedirectResponse(
        oidc.authorize_url(state=state, nonce=nonce, code_challenge=_pkce_challenge(verifier)),
        status_code=status.HTTP_302_FOUND,
    )
    response.set_cookie(
        _FLOW_COOKIE,
        _sign_flow(state, nonce, verifier),
        max_age=settings.sso_state_ttl_seconds,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",  # sent on the IdP's top-level GET redirect back to us
        path="/",
    )
    return response


@router.get("/callback", response_model=TokenOut)
async def sso_callback(
    code: str,
    state: str,
    request: Request,
    response: Response,
    oidc: OIDCClient = Depends(get_oidc),
    conn: asyncpg.Connection = Depends(get_conn),
) -> TokenOut:
    if not oidc.enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sso is not configured")
    flow = _verify_flow(request.cookies.get(_FLOW_COOKIE), state)
    if flow is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid or expired sso state")
    # One-time: the flow cookie is spent whether or not the exchange succeeds.
    response.delete_cookie(_FLOW_COOKIE, path="/", secure=_cookie_secure(), httponly=True)
    try:
        claims = await oidc.exchange_code(code, code_verifier=flow["cv"], nonce=flow["nonce"])
    except Exception as exc:  # noqa: BLE001 — surface upstream failure as 401
        log.warning("sso exchange failed: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sso exchange failed") from exc

    # Note: SSO users join the first (normally the only) organization; mapping
    # IdP claims to one of several organizations is not implemented.
    orgs = await OrganizationRepo(conn).list()
    org_id = orgs[0].id if orgs else None

    try:
        user = await AuthService(conn).resolve_sso_user(
            claims, org_id=org_id, default_role=settings.oidc_default_role
        )
    except SSOLinkError as exc:
        await _audit(conn, "sso.login_refused", org_id, None, claims.email or claims.subject)
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    await _audit(conn, "sso.login", user.org_id, user.id, user.email)

    tokens = await AuthService(conn).issue_tokens(user)
    return TokenOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
    )


async def _audit(conn: Any, action: str, org_id: Any, actor: Any, target: str) -> None:
    try:
        await AuditRepo(conn).record(action, org_id=org_id, actor_user_id=actor, target=target)
    except Exception:  # noqa: BLE001 — auditing is best-effort, never block auth
        pass
