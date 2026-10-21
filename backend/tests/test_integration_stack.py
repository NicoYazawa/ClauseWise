"""Integration smoke against the real docker stack: MySQL / Elasticsearch / Redis / Celery broker.

Opt-in: run with STACK_INTEGRATION=1 (and the compose stack up) from backend/:

    STACK_INTEGRATION=1 .venv/Scripts/python.exe -m pytest tests/test_integration_stack.py

Connection targets are the host-published loopback ports (see docker-compose.yml);
credentials are read from the project root .env — never asserted in output.
"""
import os
import pathlib
from urllib.parse import quote
from urllib.request import Request, urlopen

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("STACK_INTEGRATION") != "1",
    reason="set STACK_INTEGRATION=1 to run against the local docker stack",
)

ROOT = pathlib.Path(__file__).resolve().parents[2]
HOST = "127.0.0.1"


def _root_env() -> dict:
    env: dict = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env.setdefault(key.strip(), value.strip())
    missing = [k for k in ("MYSQL_ROOT_PASSWORD", "ES_PASSWORD", "REDIS_PASSWORD") if not env.get(k)]
    assert not missing, f"root .env missing required secrets: {missing}"
    return env


def test_mysql_accepts_authenticated_connection():
    pymysql = pytest.importorskip("pymysql")
    env = _root_env()
    connection = pymysql.connect(
        host=HOST, port=int(env.get("MYSQL_HOST_PORT", "13306")),
        user="root", password=env["MYSQL_ROOT_PASSWORD"], database=env.get("MYSQL_DATABASE", "contract_compliance"),
        connect_timeout=5,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            assert cursor.fetchone()[0] == 1
    finally:
        connection.close()


def test_es_rejects_anonymous_and_accepts_basic_auth():
    env = _root_env()
    base = f"http://{HOST}:{env.get('ES_HOST_PORT', '19200')}"
    with pytest.raises(Exception) as denied:
        urlopen(Request(base + "/_cluster/health"), timeout=5)
        raise AssertionError("anonymous ES access must fail")
    assert getattr(denied.value, "code", None) in (401, 403)
    request = Request(base + "/_cluster/health")
    request.add_header("Authorization", "Basic " + __import__("base64").b64encode(
        f"elastic:{env['ES_PASSWORD']}".encode()).decode())
    with urlopen(request, timeout=5) as response:
        assert response.status == 200


def test_redis_rejects_anonymous_and_accepts_requirepass():
    redis = pytest.importorskip("redis")
    env = _root_env()
    port = int(env.get("REDIS_HOST_PORT", "16379"))
    anonymous = redis.Redis(host=HOST, port=port, socket_connect_timeout=5)
    with pytest.raises(redis.AuthenticationError):
        anonymous.ping()
    authed = redis.Redis(host=HOST, port=port, password=env["REDIS_PASSWORD"], socket_connect_timeout=5)
    assert authed.ping() is True


def test_celery_worker_responds_over_authenticated_broker():
    from celery import Celery

    env = _root_env()
    broker = f"redis://:{quote(env['REDIS_PASSWORD'], safe='')}@{HOST}:{env.get('REDIS_HOST_PORT', '16379')}/0"
    probe = Celery(broker=broker)
    probe.conf.broker_connection_retry_on_startup = True
    replies = probe.control.ping(timeout=8)
    assert replies, "no Celery worker responded on the broker (is the worker container up?)"


def test_mysql_real_schema_constraints_and_transactions():
    """Real MySQL constraint / transaction / charset behavior (not representable by the SQLite dialect patch; runs on an isolated scratch DB for repeatability)."""
    pymysql = pytest.importorskip("pymysql")
    env = _root_env()
    port = int(env.get("MYSQL_HOST_PORT", "13306"))
    admin = pymysql.connect(host=HOST, port=port, user="root", password=env["MYSQL_ROOT_PASSWORD"],
                            connect_timeout=5, charset="utf8mb4")
    try:
        with admin.cursor() as cur:
            cur.execute("DROP DATABASE IF EXISTS clausewise_it")
            cur.execute("CREATE DATABASE clausewise_it CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        admin.commit()
    finally:
        admin.close()

    conn = pymysql.connect(host=HOST, port=port, user="root", password=env["MYSQL_ROOT_PASSWORD"],
                           database="clausewise_it", connect_timeout=5, charset="utf8mb4")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE it_contract ("
                " id BIGINT AUTO_INCREMENT PRIMARY KEY,"
                " title VARCHAR(128) NOT NULL,"
                " flag TINYINT NOT NULL DEFAULT 0,"
                " meta JSON NULL,"
                " created_at DATETIME NULL"
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
            )
        # strict mode: the NULL constraint must be enforced (a real constraint not verifiable under the SQLite patch)
        with pytest.raises(pymysql.err.IntegrityError):
            with conn.cursor() as cur:
                cur.execute("INSERT INTO it_contract (title) VALUES (NULL)")
        conn.rollback()
        # utf8mb4 Chinese round-trip + auto-increment + TINYINT/JSON
        with conn.cursor() as cur:
            cur.execute("INSERT INTO it_contract (title, flag, meta) VALUES (%s, %s, %s)",
                        ("服务器设备采购合同", 1, '{"risk": "high"}'))
            cur.execute("SELECT id, title, flag, meta FROM it_contract")
            row = cur.fetchone()
        conn.commit()
        assert row[0] == 1 and row[1] == "服务器设备采购合同" and int(row[2]) == 1
    finally:
        conn.close()
        admin = pymysql.connect(host=HOST, port=port, user="root", password=env["MYSQL_ROOT_PASSWORD"],
                                connect_timeout=5)
        try:
            with admin.cursor() as cur:
                cur.execute("DROP DATABASE IF EXISTS clausewise_it")
            admin.commit()
        finally:
            admin.close()
