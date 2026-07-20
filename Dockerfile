# OmniEvolve Sandbox Image
# 用于 DockerBackend 安全执行候选代码的最小 Python 镜像
#
# 参考 OpenEvolve 的 Docker usage 模式：
#   - 非 root 用户运行
#   - 最小依赖
#   - 只读文件系统 + tmpfs 可写工作区

FROM python:3.12-slim

# 创建非 root 用户
RUN groupadd -r sandbox && useradd -r -g sandbox -m -s /bin/bash sandbox

# 工作区（运行时挂载 tmpfs）
RUN mkdir -p /workspace && chown sandbox:sandbox /workspace

# 最小依赖（按需在运行时安装）
RUN pip install --no-cache-dir pytest==8.3.0

# 切换到非 root 用户
USER sandbox
WORKDIR /workspace

# 默认入口：由 DockerBackend 通过 command override 控制
CMD ["python", "-c", "print('OmniEvolve sandbox ready')"]
