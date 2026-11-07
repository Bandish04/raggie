# SPDX-License-Identifier: Apache-2.0

"""Real client address behind trusted reverse proxies.

X-Forwarded-For / X-Forwarded-Proto are attacker-controlled unless the direct
peer is one of our own proxies (TRUSTED_PROXY_CIDRS: the web tier, ingress).
Only then are they honoured; otherwise the socket peer is the client.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache

from starlette.requests import Request

from raggie_control_plane.config import settings

_Network = ipaddress.IPv4Network | ipaddress.IPv6Network


@lru_cache(maxsize=8)
def _parse_cidrs(raw: str) -> tuple[_Network, ...]:
    return tuple(
        ipaddress.ip_network(part.strip(), strict=False) for part in raw.split(",") if part.strip()
    )


def _is_trusted(addr: str, networks: tuple[_Network, ...]) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in net for net in networks)


def _peer(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def client_ip(request: Request) -> str:
    """The originating client IP. Walks X-Forwarded-For right-to-left (the
    entries our proxies appended), skipping trusted hops; the first untrusted
    hop is the client. A spoofed left-most entry is therefore never used unless
    every hop is a trusted proxy."""
    peer = _peer(request)
    networks = _parse_cidrs(settings.trusted_proxy_cidrs)
    if not _is_trusted(peer, networks):
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    for hop in reversed(hops):
        if not _is_trusted(hop, networks):
            return hop
    return hops[0] if hops else peer


def is_https(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    if not _is_trusted(_peer(request), _parse_cidrs(settings.trusted_proxy_cidrs)):
        return False
    proto = request.headers.get("x-forwarded-proto", "")
    return proto.split(",")[0].strip().lower() == "https"
