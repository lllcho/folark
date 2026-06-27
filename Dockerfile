# ---------- 构建阶段 ----------
FROM python:3.12-slim AS builder

WORKDIR /build

# 使用清华 PyPI 镜像加速下载（pip 和 uv 均生效）
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# 安装 uv（极速包管理器，复用项目的 uv.lock）
RUN pip install --no-cache-dir uv

# 第 1 层缓存：只复制依赖定义文件，利用 Docker 层缓存
# 只要 pyproject.toml / uv.lock 不变，此层就不会重跑
COPY README.md pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# 第 2 层：复制应用源码后再次同步（此时只安装项目自身，极快）
COPY app/ ./app/
COPY static/ ./static/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---------- 运行阶段 ----------
FROM python:3.12-slim AS runtime

# OCI 标签
LABEL org.opencontainers.image.title="folark" \
      org.opencontainers.image.description="本地优先的个人文档管理工具" \
      org.opencontainers.image.licenses="AGPL-3.0"

WORKDIR /app

# 复制虚拟环境（uv 默认创建在项目目录的 .venv 下）
COPY --from=builder /build/.venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    VIRTUAL_ENV="/opt/venv"

# 复制应用代码
COPY app/ ./app/
COPY static/ ./static/

# 暴露端口
EXPOSE 8890

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8890/')" || exit 1

# 数据持久化卷
VOLUME ["/app/data"]

# 启动应用（用 python -m 而非直接 uvicorn，避免 venv shebang 路径失效）
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8890"]
