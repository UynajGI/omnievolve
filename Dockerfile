# OmniEvolve Sandbox Image
# P2: 多阶段构建 + HEALTHCHECK + hadolint 合规
#
# 用于 DockerBackend 安全执行候选代码的最小 Python 镜像。
# 参考 OpenEvolve 的 Docker usage 模式：
#   - 非 root 用户运行
#   - 最小依赖
#   - 只读文件系统 + tmpfs 可写工作区
#   - 多阶段构建减小编译层残留

# ── 构建阶段：安装 pip 依赖 ─────────────────────────────────
FROM python:3.12-slim AS builder

# hadolint: DL3042 (no-cache-dir), DL3013 (pin versions)
COPY requirements-sandbox.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements-sandbox.txt

# ── 运行时阶段：最小镜像 ─────────────────────────────────
FROM python:3.12-slim

LABEL org.opencontainers.image.title="OmniEvolve Sandbox"
LABEL org.opencontainers.image.description="Secure execution environment for candidate code evaluation"
LABEL org.opencontainers.image.version="0.2.0"

# 创建非 root 用户
RUN groupadd -r sandbox && useradd -r -g sandbox -m -s /bin/false sandbox

# 从构建阶段复制 site-packages
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages

# 工作区（运行时挂载 tmpfs）
RUN mkdir -p /workspace && chown sandbox:sandbox /workspace

# HEALTHCHECK — 每 30s 检查 Python 可用
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# 安全加固
USER sandbox
WORKDIR /workspace

# 默认入口：由 DockerBackend 通过 command override 控制
CMD ["python", "-c", "print('OmniEvolve sandbox ready')"]
