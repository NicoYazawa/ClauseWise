"""Audit regression: the client IP in the audit trail must identify the real source, not the reverse proxy.

Production goes through nginx, so request.client.host is the nginx container IP. These tests pin the
resolution order (trusted-proxy forwarded headers -> peer address fallback) and the spoofing boundary.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.request_ctx import client_info, client_ip

NGINX_IP = "172.18.0.4"  # docker bridge peer == nginx container
REAL_IP = "203.0.113.37"


def _req(peer: str | None, **headers: str):
    """Minimal request stub: client_info only reads client.host + headers.get."""
    return SimpleNamespace(client=SimpleNamespace(host=peer) if peer else None, headers=headers)


class TestTrustedProxy:
    def test_x_real_ip_wins_behind_nginx(self):
        assert client_ip(_req(NGINX_IP, **{"x-real-ip": REAL_IP})) == REAL_IP

    def test_forwarded_for_chain_takes_leftmost(self):
        req = _req(NGINX_IP, **{"x-forwarded-for": f"{REAL_IP}, 10.1.1.1"})
        assert client_ip(req) == REAL_IP

    def test_x_real_ip_preferred_over_forwarded_for(self):
        req = _req(NGINX_IP, **{"x-real-ip": REAL_IP, "x-forwarded-for": "198.51.100.9"})
        assert client_ip(req) == REAL_IP

    def test_loopback_and_private_peers_are_trusted(self):
        assert client_ip(_req("127.0.0.1", **{"x-real-ip": REAL_IP})) == REAL_IP
        assert client_ip(_req("10.1.2.3", **{"x-real-ip": REAL_IP})) == REAL_IP
        assert client_ip(_req("fd00::1", **{"x-real-ip": REAL_IP})) == REAL_IP

    def test_no_forwarded_header_falls_back_to_peer(self):
        assert client_ip(_req(NGINX_IP)) == NGINX_IP

    def test_ipv6_with_port_is_normalized(self):
        assert client_ip(_req(NGINX_IP, **{"x-real-ip": "[2001:db8::1]:443"})) == "2001:db8::1"

    def test_ipv4_with_port_is_normalized(self):
        assert client_ip(_req(NGINX_IP, **{"x-real-ip": "198.51.100.7:51234"})) == "198.51.100.7"


class TestSpoofingBoundary:
    # NOTE: do not use RFC 5737 documentation ranges (203.0.113.x / 198.51.100.x) as "public" peers here --
    # Python's ipaddress module classifies every IANA-reserved block as is_private, so they count as trusted.
    @pytest.mark.parametrize("peer", ["8.8.8.8", "1.1.1.1", "114.114.114.114"])
    def test_public_peer_cannot_forge_forwarded_headers(self, peer):
        """A client hitting the app directly (not via an intranet proxy) must not dictate its own IP."""
        req = _req(peer, **{"x-real-ip": "9.9.9.9", "x-forwarded-for": "9.9.9.9"})
        assert client_ip(req) == peer

    @pytest.mark.parametrize("forged", [
        "not-an-ip",
        "999.999.999.999",
        "'; DROP TABLE audit_log; --",
        "1.2.3.4\r\nX-Injected: 1",
        "   ",
    ])
    def test_invalid_forwarded_value_is_rejected(self, forged):
        assert client_ip(_req(NGINX_IP, **{"x-real-ip": forged})) == NGINX_IP

    def test_missing_client_is_unknown(self):
        assert client_ip(_req(None)) == "-"

    def test_non_ip_peer_is_returned_as_is(self):
        """TestClient's peer is the literal 'testclient' -- keep it rather than losing the value."""
        assert client_ip(_req("testclient", **{"x-real-ip": REAL_IP})) == "testclient"


class TestClientInfo:
    def test_user_agent_is_truncated(self):
        ip, ua = client_info(_req(NGINX_IP, **{"x-real-ip": REAL_IP, "user-agent": "A" * 500}))
        assert (ip, len(ua)) == (REAL_IP, 120)

    def test_missing_user_agent_is_unknown(self):
        _, ua = client_info(_req(NGINX_IP))
        assert ua == "-"


class TestApiModulesDelegate:
    @pytest.mark.parametrize("module", [
        "app.api.v1.auth", "app.api.v1.contracts", "app.api.v1.knowledge",
        "app.api.v1.reviews", "app.api.v1.system", "app.api.v1.workflows",
    ])
    def test_no_local_duplicate_implementation(self, module):
        """Guards against re-introducing a per-module `request.client.host` copy (the original defect)."""
        import importlib

        assert importlib.import_module(module)._client_info is client_info


class TestAuditTrailIntegration:
    def test_login_audit_records_resolved_ip(self, db, session_factory):
        """End-to-end through a real request whose peer is the nginx container: audit must store the real IP."""
        from fastapi.testclient import TestClient

        from app.core.security import hash_password
        from app.db.session import get_db
        from app.main import app
        from app.models.knowledge import AuditLog
        from tests import helpers

        def _override_db():
            s = session_factory()
            try:
                yield s
            finally:
                s.close()

        helpers.make_user(db, username="bob", password_hash=hash_password("Sup3rSecretPassw0rd"))
        db.commit()
        app.dependency_overrides[get_db] = _override_db
        c = None
        try:
            # No `with` block: that would trigger the real lifespan (preflight) -- see conftest's client fixture
            c = TestClient(app, client=(NGINX_IP, 5000))
            resp = c.post("/api/v1/auth/login",
                          json={"username": "bob", "password": "Sup3rSecretPassw0rd"},  # gitleaks:allow -- isolated test fixture
                          headers={"X-Real-IP": REAL_IP, "X-Forwarded-For": f"{REAL_IP}, {NGINX_IP}"})
            assert resp.status_code == 200, resp.text
        finally:
            if c is not None:
                c.close()
            app.dependency_overrides.clear()
        db.expire_all()
        record = db.query(AuditLog).filter(AuditLog.action == "login").one()
        assert record.detail["ip"] == REAL_IP
