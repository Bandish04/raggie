# SPDX-License-Identifier: Apache-2.0

"""OIDC client behind the IdentityProvider seam.

Authorization-code flow with PKCE (S256) and a nonce: redirect to the IdP, then
exchange the code (+ code_verifier) for tokens and validate the ID token (iss,
aud, exp, nonce; signature via JWKS when OIDC_JWKS_URL is set). The resulting
(issuer, subject) is the stable identity key; email + email_verified are only
used for a first-time link. SAML plugs into the same provision path via its ACS
endpoint — only the assertion parsing differs.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from raggie_control_plane.config import settings

# Asymmetric algorithms only: never "none", never HS* (the client secret is not
# a signing key we accept for identity assertions).
_ID_TOKEN_ALGS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384"]
_REQUIRED_CLAIMS = ["iss", "aud", "sub", "exp", "iat"]


class OIDCError(Exception):
    """The IdP response could not be trusted (bad token, nonce, issuer, …)."""


@dataclass(frozen=True)
class OIDCClaims:
    subject: str
    email: str | None
    email_verified: bool
    issuer: str


def _truthy(value: Any) -> bool:
    # Some IdPs (e.g. Cognito) serialize email_verified as the string "true".
    return value is True or (isinstance(value, str) and value.lower() == "true")


class OIDCClient:
    def __init__(
        self, *, timeout: float = 10.0, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._timeout = timeout
        self._transport = transport

    @property
    def enabled(self) -> bool:
        return settings.oidc_enabled and bool(settings.oidc_authorize_url)

    def authorize_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        params = {
            "response_type": "code",
            "client_id": settings.oidc_client_id,
            "redirect_uri": settings.oidc_redirect_url,
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        sep = "&" if "?" in settings.oidc_authorize_url else "?"
        return f"{settings.oidc_authorize_url}{sep}{urlencode(params)}"

    async def exchange_code(self, code: str, *, code_verifier: str, nonce: str) -> OIDCClaims:
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            token_resp = await client.post(
                settings.oidc_token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.oidc_redirect_url,
                    "client_id": settings.oidc_client_id,
                    "client_secret": settings.oidc_client_secret,
                    "code_verifier": code_verifier,
                },
                headers={"Accept": "application/json"},
            )
            token_resp.raise_for_status()
            tokens = token_resp.json()
            id_token = tokens.get("id_token")
            if not id_token:
                raise OIDCError("token response has no id_token")
            claims = await self._verify_id_token(client, id_token, nonce)

            email = claims.get("email")
            email_verified = _truthy(claims.get("email_verified"))
            if not email and settings.oidc_userinfo_url and tokens.get("access_token"):
                info = await self._userinfo(client, tokens["access_token"])
                # Userinfo must describe the same principal as the ID token.
                if str(info.get("sub")) != str(claims["sub"]):
                    raise OIDCError("userinfo subject does not match the id token")
                email = info.get("email")
                email_verified = _truthy(info.get("email_verified"))

        return OIDCClaims(
            subject=str(claims["sub"]),
            email=str(email) if email else None,
            email_verified=email_verified,
            issuer=str(claims["iss"]),
        )

    async def _userinfo(self, client: httpx.AsyncClient, access_token: str) -> dict:
        resp = await client.get(
            settings.oidc_userinfo_url, headers={"Authorization": f"Bearer {access_token}"}
        )
        resp.raise_for_status()
        return resp.json()

    async def _verify_id_token(
        self, client: httpx.AsyncClient, id_token: str, nonce: str
    ) -> dict[str, Any]:
        options: Any = {"require": _REQUIRED_CLAIMS}  # jwt.types.Options (TypedDict)
        issuer = settings.oidc_issuer or None
        try:
            if settings.oidc_jwks_url:
                key = await self._signing_key(client, id_token)
                claims = jwt.decode(
                    id_token,
                    key,
                    algorithms=_ID_TOKEN_ALGS,
                    audience=settings.oidc_client_id,
                    issuer=issuer,
                    options=options,
                )
            else:
                # No JWKS configured: the token came straight from the token
                # endpoint over TLS (OIDC Core §3.1.3.7), so the signature is not
                # re-checked — every other claim still is.
                claims = jwt.decode(
                    id_token,
                    algorithms=_ID_TOKEN_ALGS,
                    audience=settings.oidc_client_id,
                    issuer=issuer,
                    options={
                        **options,
                        "verify_signature": False,
                        "verify_aud": True,
                        "verify_iss": issuer is not None,
                        "verify_exp": True,
                        "verify_iat": True,
                    },
                )
        except jwt.PyJWTError as exc:
            raise OIDCError(f"invalid id token: {exc}") from exc
        if not hmac.compare_digest(str(claims.get("nonce", "")).encode(), nonce.encode()):
            raise OIDCError("id token nonce mismatch")
        return claims

    async def _signing_key(self, client: httpx.AsyncClient, id_token: str) -> jwt.PyJWK:
        try:
            kid = jwt.get_unverified_header(id_token).get("kid")
        except jwt.PyJWTError as exc:
            raise OIDCError("malformed id token header") from exc
        resp = await client.get(settings.oidc_jwks_url, headers={"Accept": "application/json"})
        resp.raise_for_status()
        keys = jwt.PyJWKSet.from_dict(resp.json()).keys
        for key in keys:
            if kid is None or key.key_id == kid:
                return key
        raise OIDCError("no JWKS key matches the id token")
