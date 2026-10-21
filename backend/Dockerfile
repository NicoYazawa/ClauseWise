# syntax=docker/dockerfile:1.7
FROM python:3.13-slim AS base

# 构建期 PyPI 偶发超时：放宽超时并加重试，避免锁文件变更导致整层重建时失败
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_HTTP_TIMEOUT=120 \
    UV_HTTP_RETRIES=5 \
    PATH="/app/.venv/bin:$PATH" \
    TZ=Asia/Shanghai

# uv（版本与开发机一致）
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /usr/local/bin/

WORKDIR /app

# 说明：python:3.13-slim 已含 ca-certificates；PyMuPDF 2.x 官方 wheel 自带 MuPDF，
# 实测无需 libgl/libgomp，故此处不引入 apt（避免 Debian 源下载拖慢构建）。

# 依赖源可覆盖：默认走官方 PyPI；容器网络无法直连 files.pythonhosted.org 时，
# 在 .env 设置 UV_INDEX_URL 指向可用镜像即可（如 https://mirrors.aliyun.com/pypi/simple/）
ARG UV_INDEX_URL=""
ENV UV_DEFAULT_INDEX=${UV_INDEX_URL} \
    UV_INDEX_URL=${UV_INDEX_URL}

# 先只复制依赖清单 → 依赖层可被缓存，代码变更不会触发重装
COPY pyproject.toml uv.lock ./
# cache mount：uv 下载缓存跨构建复用。锁文件变更会重建本层，有它只需增量下载，
# 否则每次都要把 100+ 个 wheel 全部重下（本机实测可达数分钟）。
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

COPY app ./app
COPY scripts ./scripts
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh \
    && mkdir -p /app/data/logs/app /app/data/logs/audit /app/data/storage

EXPOSE 8000

# 健康检查用 python 自带 urllib，避免额外安装 curl
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=10 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"]

ENTRYPOINT ["/app/docker-entrypoint.sh"]
# --proxy-headers: only the nginx reverse proxy can reach the container (host port bound to 127.0.0.1), so trust its
# X-Real-IP / X-Forwarded-For; otherwise request.client.host is the nginx container IP and audit logs cannot identify
# the source (nginx's container IP is dynamic, hence --forwarded-allow-ips "*";
# app.core.request_ctx.client_info adds a private-network/valid-IP check as a second layer regardless of this flag)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]