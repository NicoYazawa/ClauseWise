#!/bin/sh
# Alertmanager 启动脚本：
# 共享令牌通过环境变量注入生成配置，避免把 ALERT_INGEST_TOKEN 明文写进仓库。
# Alertmanager 无法携带 JWT，回调应用时用查询参数 token 鉴权。
set -e

if [ -z "${ALERT_INGEST_TOKEN}" ]; then
  echo "[alertmanager] 警告：ALERT_INGEST_TOKEN 为空，回调将被 API 拒绝（请检查 .env）" >&2
fi

cat > /tmp/alertmanager.yml <<EOF
route:
  receiver: clausewise
  group_by: ["alertname"]
  group_wait: 10s
  group_interval: 2m
  repeat_interval: 30m

receivers:
  - name: clausewise
    webhook_configs:
      - url: http://api:8000/api/v1/alerts/prometheus?token=${ALERT_INGEST_TOKEN}
        send_resolved: false
        max_alerts: 10
EOF

exec /bin/alertmanager --config.file=/tmp/alertmanager.yml --storage.path=/alertmanager
