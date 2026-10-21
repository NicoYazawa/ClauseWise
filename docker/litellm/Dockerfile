# syntax=docker/dockerfile:1.7
# LiteLLM 模型网关镜像
#
# 为什么不用官方 ghcr.io/berriai/litellm：
#   本机到 ghcr.io 不可达（实测 HEAD manifests 超时），而 python:3.13-slim 已在本地镜像库、
#   pypi 可达。因此直接 pip 安装，构建过程不依赖任何镜像仓库网络。
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 锁定版本：避免 pip 在数百个历史版本间回溯求解（实测比下载本身还慢），同时保证构建可复现
ARG LITELLM_VERSION=1.106.0
# pip 缓存跨构建复用：版本不变时不会重复下载 100+ 个依赖
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --timeout 60 --retries 5 "litellm[proxy]==${LITELLM_VERSION}"

# litellm[proxy] 未包含 prometheus_client，缺失会导致 callbacks: ["prometheus"] 启动即崩溃。
# 独立成层：后续调整指标依赖不会让上面 100 个包的层失效。
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --timeout 60 --retries 5 prometheus-client

EXPOSE 4000

CMD ["litellm", "--config", "/app/config.yaml", "--host", "0.0.0.0", "--port", "4000"]
