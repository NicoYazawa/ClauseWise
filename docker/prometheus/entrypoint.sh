#!/bin/sh
# Prometheus 启动脚本：
# 1) 把 LITELLM_MASTER_KEY 写入 credentials_file（Prometheus 配置不支持环境变量替换，
#    故在启动时生成文件，避免密钥明文入库）
# 2) 以正常参数启动 prometheus
set -e

if [ -n "${LITELLM_MASTER_KEY}" ]; then
  printf '%s' "${LITELLM_MASTER_KEY}" > /tmp/litellm_key
  chmod 600 /tmp/litellm_key
else
  echo "[prometheus] 警告：LITELLM_MASTER_KEY 为空，网关指标抓取将返回 401" >&2
fi

exec /bin/prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/prometheus \
  --storage.tsdb.retention.time=15d \
  --web.enable-lifecycle
