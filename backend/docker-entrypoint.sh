#!/bin/sh
# ClauseWise 后端容器入口：等待依赖就绪 → 可选初始化数据库 → 启动服务
set -e

echo "[entrypoint] 等待 MySQL（${MYSQL_HOST:-mysql}:${MYSQL_PORT:-3306}）..."
python - <<'PY'
import os
import socket
import sys
import time

host = os.getenv("MYSQL_HOST", "mysql")
port = int(os.getenv("MYSQL_PORT", "3306"))
deadline = time.time() + 180
while time.time() < deadline:
    try:
        socket.create_connection((host, port), timeout=2).close()
        print("[entrypoint] MySQL TCP 就绪")
        sys.exit(0)
    except OSError:
        time.sleep(2)
print("[entrypoint] 等待 MySQL 超时")
sys.exit(1)
PY

if [ "${WAIT_TABLES:-0}" = "1" ]; then
  echo "[entrypoint] 等待数据表就绪..."
  python - <<'PY'
import sys
import time

from sqlalchemy import create_engine, text

from app.core.config import settings

deadline = time.time() + 240
while time.time() < deadline:
    try:
        engine = create_engine(settings.sqlalchemy_database_uri)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1 FROM `user` LIMIT 1"))
        engine.dispose()
        print("[entrypoint] 数据表就绪")
        sys.exit(0)
    except Exception:
        time.sleep(3)
print("[entrypoint] 等待数据表超时")
sys.exit(1)
PY
fi

if [ "${INIT_DB:-0}" = "1" ]; then
  echo "[entrypoint] 执行数据库初始化（幂等：建库/建表/种子数据/ES 索引）..."
  python scripts/init_db.py || echo "[entrypoint] init_db 执行失败，继续启动（详情见上方输出）"
fi

exec "$@"
