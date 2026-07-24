"""Headless LLM Provider — 通过 CLI 子进程连接 agentic coding 工具.

从 ShinkaEvolve headless.py 精简移植。
支持 "headless/agent@model" 格式的模型名，路由到 CLI subprocess 执行。
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class HeadlessModel:
    """解析后的 headless 模型描述."""

    agent: str  # claude-code, codex, etc.
    model: str | None  # 底层模型
    params: dict[str, str]  # 额外参数 (effort=high 等)


def parse_headless_model(model_str: str) -> HeadlessModel:
    """解析 "headless/agent@model?effort=high" 格式.

    Examples:
        "headless/claude-code" → agent="claude-code", model=None
        "headless/codex@gpt-4o" → agent="codex", model="gpt-4o"
        "headless/claude-code@sonnet?effort=high" → agent="claude-code", model="sonnet"
    """
    # 去掉 headless/ 前缀
    spec = model_str.replace("headless/", "").replace("headless:", "")

    # 分离 query params
    params: dict[str, str] = {}
    if "?" in spec:
        spec, query = spec.split("?", 1)
        for pair in query.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                params[k] = v

    # 分离 agent 和 model
    agent = spec
    model = None
    if "@" in spec:
        agent, model = spec.split("@", 1)

    return HeadlessModel(agent=agent, model=model, params=params)


def check_headless_available(agent: str) -> bool:
    """检查 headless agent 是否可用."""
    commands = {
        "claude-code": "claude",
        "codex": "codex",
        "cursor": "cursor-agent",
        "aider": "aider",
    }
    cmd = commands.get(agent, agent)
    try:
        result = subprocess.run(
            ["which", cmd],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _build_command(hm: HeadlessModel, prompt_file: str | None = None) -> list[str]:
    """构建 CLI 命令.

    Args:
        hm: 解析后的 headless 模型描述
        prompt_file: prompt 文件路径（aider 用 --message-file）
    """
    commands: dict[str, list[str]] = {
        "claude-code": ["claude", "--print"],
        "codex": ["codex", "--quiet"],
        "aider": ["aider", "--no-auto-commits", "--message-file"],
        "cursor": ["cursor-agent", "--print"],
    }

    base = commands.get(hm.agent, [hm.agent])
    cmd = list(base)

    if hm.agent == "claude-code" and hm.model:
        cmd.extend(["--model", hm.model])
    elif hm.agent == "codex" and hm.model:
        cmd.extend(["--model", hm.model])

    # aider 需要 --message-file 参数指向 prompt 文件
    if hm.agent == "aider" and prompt_file:
        cmd.append(prompt_file)

    return cmd


def query_headless(
    prompt: str,
    model_str: str,
    timeout: int = 120,
) -> str:
    """通过 CLI 子进程执行 LLM 查询.

    Args:
        prompt: 输入提示
        model_str: "headless/agent@model" 格式
        timeout: 超时秒数

    Returns:
        CLI stdout 作为响应
    """
    hm = parse_headless_model(model_str)

    if not check_headless_available(hm.agent):
        raise RuntimeError(
            f"Headless agent '{hm.agent}' not found. "
            f"Install it or check PATH."
        )

    env = os.environ.copy()
    # 安全：不传入敏感环境变量
    env.pop("OPENAI_API_KEY", None)
    env.pop("ANTHROPIC_API_KEY", None)

    try:
        result = subprocess.run(
            _build_command(hm, ""),
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

        if result.returncode != 0:
            logger.warning(
                "Headless agent %s returned code %d: %s",
                hm.agent,
                result.returncode,
                result.stderr[:500],
            )

        return result.stdout.strip()

    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"Headless agent '{hm.agent}' timed out after {timeout}s"
        )


async def query_headless_async(
    prompt: str,
    model_str: str,
    timeout: int = 120,
) -> str:
    """异步版本 — 使用 asyncio.create_subprocess_exec."""
    import asyncio

    hm = parse_headless_model(model_str)

    if not check_headless_available(hm.agent):
        raise RuntimeError(f"Headless agent '{hm.agent}' not found.")

    env = os.environ.copy()

    try:
        proc = await asyncio.create_subprocess_exec(
            *_build_command(hm, ""),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=prompt.encode()),
            timeout=timeout,
        )

        if proc.returncode != 0:
            logger.warning(
                "Headless %s returned %d: %s",
                hm.agent,
                proc.returncode,
                stderr.decode()[:500],
            )

        return stdout.decode().strip()

    except TimeoutError:
        raise RuntimeError(f"Headless agent '{hm.agent}' timed out")
