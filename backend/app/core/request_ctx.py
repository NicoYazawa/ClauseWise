"""Request source identification (client IP / User-Agent) for audit trails.

Why this module exists: production goes through the nginx reverse proxy (frontend/Dockerfile -> api),
so ``request.client.host`` is the **proxy container IP** and every audit record would share the same
value, making audit logs (3.5.4, retained >= 3 years) useless for tracing. nginx does pass through
X-Real-IP / X-Forwarded-For, but those are attacker-controllable, so they may only be trusted when the
direct peer is inside the perimeter.

Rules:
- only loopback / private / link-local peers are treated as a trusted proxy (nginx, ingress, local dev proxy);
- forwarded header values must parse as a valid IP (rejects forged / oversized junk, and keeps arbitrary
  text out of the audit trail);
- otherwise fall back to the peer address itself.
"""
from ipaddress import ip_address

from fastapi import Request

UNKNOWN = "-"
MAX_UA_LENGTH = 120


def _parse_ip(value: str | None) -> str | None:
    """Normalize one IP candidate (strips port / picks the leftmost XFF entry); None if not a valid IP."""
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    # X-Forwarded-For is a chain "client, proxy1, proxy2"; the leftmost entry is the original client
    host = candidate.split(",")[0].strip()
    if host.startswith("["):  # [::1]:8080
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:  # 10.0.0.1:54321 (IPv4 with port); a bare IPv6 has multiple colons
        host = host.rsplit(":", 1)[0]
    try:
        return str(ip_address(host))
    except ValueError:
        return None


def _is_trusted_proxy(host: str | None) -> bool:
    """Loopback / private network / link-local == inside the perimeter; public addresses are never trusted."""
    if not host:
        return False
    try:
        addr = ip_address(host.strip())
    except ValueError:
        return False
    return addr.is_loopback or addr.is_private or addr.is_link_local


def client_ip(request: Request) -> str:
    """Real client IP: forwarded headers (trusted proxy only) with fallback to the direct peer address."""
    peer = request.client.host if request.client else None
    if _is_trusted_proxy(peer):
        for header in ("x-real-ip", "x-forwarded-for"):
            forwarded = _parse_ip(request.headers.get(header))
            if forwarded:
                return forwarded
    parsed_peer = _parse_ip(peer)
    return parsed_peer or peer or UNKNOWN


def client_info(request: Request) -> tuple[str, str]:
    """(client IP, User-Agent) for write_audit; UA is uniformly truncated to 120 characters."""
    ua = (request.headers.get("user-agent") or UNKNOWN)[:MAX_UA_LENGTH] or UNKNOWN
    return client_ip(request), ua