#!/usr/bin/env python3
"""Open-Code-Review (ocr) MCP Server.

将 ocr CLI 的常用命令暴露为 MCP tools，供 IDE 内直接调用。
"""

from __future__ import annotations

import asyncio
import shutil

from mcp.server.fastmcp import FastMCP

# ocr 实际路径（nvm 管理）
OCR_BIN = shutil.which("ocr") or "/home/jiangyuan/.nvm/versions/node/v22.23.1/bin/ocr"
# 项目根目录
REPO_ROOT = "/home/jiangyuan/omnievolve"

mcp = FastMCP("ocr")


async def _run_ocr(*args: str, timeout: int = 120) -> str:
    """执行 ocr 命令并返回输出."""
    cmd = [OCR_BIN, *args]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=REPO_ROOT,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode(errors="replace")
        if stderr:
            err_text = stderr.decode(errors="replace")
            if proc.returncode != 0:
                output += f"\n[stderr]\n{err_text}"
        if proc.returncode != 0 and not output.strip():
            output = f"[exit code {proc.returncode}]"
        return output.strip() or "(no output)"
    except TimeoutError:
        return f"[timeout after {timeout}s] command: {' '.join(cmd)}"
    except FileNotFoundError:
        return f"[error] ocr binary not found at: {OCR_BIN}"


@mcp.tool()
async def review(
    from_ref: str = "main",
    to_ref: str = "HEAD",
    model: str | None = None,
    exclude: str | None = None,
    background: str | None = None,
    format: str = "text",
    concurrency: int = 8,
    preview: bool = False,
) -> str:
    """对 Git diff 范围做 AI 代码审查.

    Args:
        from_ref: 起始 ref（分支/tag/commit），默认 main
        to_ref: 目标 ref，默认 HEAD
        model: 覆盖默认模型（可选）
        exclude: 逗号分隔的排除模式（gitignore 风格）
        background: 需求/业务上下文说明
        format: 输出格式 text 或 json
        concurrency: 最大并发文件审查数
        preview: 仅预览将审查哪些文件，不跑 LLM
    """
    args = ["review", "-from", from_ref, "-to", to_ref, "-format", format, "-concurrency", str(concurrency)]
    if model:
        args += ["-model", model]
    if exclude:
        args += ["-exclude", exclude]
    if background:
        args += ["-background", background]
    if preview:
        args += ["-preview"]
    return await _run_ocr(*args, timeout=600)


@mcp.tool()
async def review_commit(
    commit: str = "HEAD",
    model: str | None = None,
    exclude: str | None = None,
    background: str | None = None,
    format: str = "text",
    preview: bool = False,
) -> str:
    """审查单个 commit 的改动.

    Args:
        commit: commit hash 或 ref，默认 HEAD
        model: 覆盖默认模型（可选）
        exclude: 逗号分隔的排除模式
        background: 需求/业务上下文说明
        format: 输出格式 text 或 json
        preview: 仅预览将审查哪些文件
    """
    args = ["review", "-commit", commit, "-format", format]
    if model:
        args += ["-model", model]
    if exclude:
        args += ["-exclude", exclude]
    if background:
        args += ["-background", background]
    if preview:
        args += ["-preview"]
    return await _run_ocr(*args, timeout=600)


@mcp.tool()
async def scan(
    path: str | None = None,
    model: str | None = None,
    exclude: str | None = None,
    format: str = "text",
) -> str:
    """扫描文件/目录（无需 diff，全文件审查）.

    Args:
        path: 要扫描的路径，默认整个仓库
        model: 覆盖默认模型（可选）
        exclude: 逗号分隔的排除模式
        format: 输出格式 text 或 json
    """
    args = ["scan", "-format", format]
    if path:
        args += ["--path", path]
    if model:
        args += ["-model", model]
    if exclude:
        args += ["-exclude", exclude]
    return await _run_ocr(*args, timeout=600)


@mcp.tool()
async def delegate(
    from_ref: str = "main",
    to_ref: str = "HEAD",
) -> str:
    """输出 review spec（不消耗 LLM，供宿主 agent 自行审查）.

    Args:
        from_ref: 起始 ref
        to_ref: 目标 ref
    """
    args = ["delegate", "-from", from_ref, "-to", to_ref]
    return await _run_ocr(*args, timeout=30)


@mcp.tool()
async def sessions(action: str = "list", session_id: str | None = None) -> str:
    """查看历史 review 会话.

    Args:
        action: "list" 列出所有会话, "show" 查看指定会话
        session_id: 会话 ID（action=show 时必填）
    """
    if action == "show" and session_id:
        args = ["session", "show", session_id]
    else:
        args = ["session", "list"]
    return await _run_ocr(*args, timeout=30)


@mcp.tool()
async def rules(action: str = "list") -> str:
    """查看/调试 review 规则.

    Args:
        action: "list" 列出所有规则, "check" 检查规则配置
    """
    args = ["rules", action]
    return await _run_ocr(*args, timeout=30)


@mcp.tool()
async def llm_test() -> str:
    """测试 LLM 连接是否正常."""
    return await _run_ocr("llm", "test", timeout=30)


if __name__ == "__main__":
    mcp.run(transport="stdio")
