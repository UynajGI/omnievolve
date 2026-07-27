#!/usr/bin/env python3
"""Production-oriented Open-Code-Review CLI MCP server.

Configuration (environment variables):
    OCR_MCP_BIN                 OCR executable or command name (default: ocr)
    OCR_MCP_REPO_ROOT           Repository root
    OCR_MCP_MAX_PROCESSES       Max concurrent OCR processes (default: 2)
    OCR_MCP_MAX_OUTPUT_BYTES    Retained bytes per stdout/stderr (default: 2 MiB)
    OCR_MCP_TERMINATE_GRACE     Seconds between TERM and KILL (default: 3)
    OCR_MCP_LOG_LEVEL           Python log level (default: INFO)

The server targets the stable official MCP Python SDK v1 FastMCP API.
All logs go to stderr because stdout is reserved for the stdio protocol.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import sys
import time
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.session import ServerSession
from pydantic import BaseModel, Field

SERVER_NAME = "open-code-review"
DEFAULT_REPO_ROOT = "/home/jiangyuan/omnievolve"
DEFAULT_OCR_FALLBACK = "/home/jiangyuan/.nvm/versions/node/v22.23.1/bin/ocr"
OutputFormat = Literal["text", "json"]
SessionAction = Literal["list", "show"]
RulesAction = Literal["list", "check"]


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} 必须是整数，当前值：{raw!r}") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} 必须位于 [{minimum}, {maximum}]，当前值：{value}")
    return value


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} 必须是数值，当前值：{raw!r}") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} 必须位于 [{minimum}, {maximum}]，当前值：{value}")
    return value


def _resolve_executable(value: str | None) -> Path:
    configured = (value or "ocr").strip() or "ocr"
    if os.sep in configured or (os.altsep and os.altsep in configured):
        candidate = Path(configured).expanduser().resolve()
    else:
        found = shutil.which(configured)
        candidate = Path(found or DEFAULT_OCR_FALLBACK).expanduser().resolve()
    if not candidate.is_file():
        raise RuntimeError(f"OCR 可执行文件不存在：{candidate}；请设置 OCR_MCP_BIN 或配置 PATH")
    if not os.access(candidate, os.X_OK):
        raise RuntimeError(f"OCR 文件不可执行：{candidate}")
    return candidate


@dataclass(frozen=True, slots=True)
class Settings:
    ocr_bin: Path
    repo_root: Path
    max_processes: int
    max_output_bytes: int
    terminate_grace_seconds: float

    @classmethod
    def from_env(cls) -> Settings:
        root = Path(os.getenv("OCR_MCP_REPO_ROOT", DEFAULT_REPO_ROOT)).expanduser().resolve()
        if not root.is_dir():
            raise RuntimeError(f"仓库根目录不存在：{root}；请设置 OCR_MCP_REPO_ROOT")
        return cls(
            ocr_bin=_resolve_executable(os.getenv("OCR_MCP_BIN")),
            repo_root=root,
            max_processes=_env_int("OCR_MCP_MAX_PROCESSES", 2, 1, 32),
            max_output_bytes=_env_int(
                "OCR_MCP_MAX_OUTPUT_BYTES", 2 * 1024 * 1024, 64 * 1024, 64 * 1024 * 1024
            ),
            terminate_grace_seconds=_env_float("OCR_MCP_TERMINATE_GRACE", 3.0, 0.1, 30.0),
        )


@dataclass(slots=True)
class AppState:
    settings: Settings
    process_slots: asyncio.Semaphore


class OCRCommandResult(BaseModel):
    """Successful OCR invocation."""

    ok: bool = True
    operation: str
    command: list[str] = Field(description="Redacted OCR arguments")
    exit_code: int
    duration_ms: int
    stdout: str
    stderr: str
    stdout_truncated: bool = False
    stderr_truncated: bool = False


class ServerInfo(BaseModel):
    server_name: str
    ocr_bin: str
    repo_root: str
    repo_is_git_worktree: bool
    max_processes: int
    max_output_bytes: int
    python_version: str
    platform: str


@dataclass(slots=True)
class _Captured:
    text: str
    truncated: bool
    total_bytes: int


class _BoundedCapture:
    """Drain a pipe continuously while retaining only its head and tail."""

    def __init__(self, limit: int) -> None:
        self.head_limit = max(1, limit // 2)
        self.tail_limit = max(1, limit - self.head_limit)
        self.head = bytearray()
        self.tail = bytearray()
        self.total = 0

    def feed(self, chunk: bytes) -> None:
        self.total += len(chunk)
        offset = 0
        if len(self.head) < self.head_limit:
            take = min(self.head_limit - len(self.head), len(chunk))
            self.head.extend(chunk[:take])
            offset = take
        if offset < len(chunk):
            self.tail.extend(chunk[offset:])
            if len(self.tail) > self.tail_limit:
                del self.tail[: len(self.tail) - self.tail_limit]

    def finish(self) -> _Captured:
        truncated = self.total > self.head_limit + self.tail_limit
        if truncated:
            marker = f"\n\n...[输出已截断，原始大小 {self.total} bytes]...\n\n".encode()
            raw = bytes(self.head) + marker + bytes(self.tail)
        else:
            raw = bytes(self.head) + bytes(self.tail)
        return _Captured(raw.decode("utf-8", errors="replace"), truncated, self.total)


def _configure_logging() -> None:
    level = getattr(logging, os.getenv("OCR_MCP_LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )


_configure_logging()
logger = logging.getLogger(SERVER_NAME)


@asynccontextmanager
async def app_lifespan(_: FastMCP) -> AsyncIterator[AppState]:
    settings = Settings.from_env()
    logger.info(
        "starting repo=%s bin=%s max_processes=%d",
        settings.repo_root,
        settings.ocr_bin,
        settings.max_processes,
    )
    yield AppState(settings, asyncio.Semaphore(settings.max_processes))
    logger.info("stopped")


mcp = FastMCP(
    SERVER_NAME,
    instructions=(
        "调用 Open-Code-Review 审查 OmniEvolve 仓库。"
        "建议先使用 preview 或 delegate 确认范围。"
        "scan 只能读取仓库根目录内部路径。"
    ),
    lifespan=app_lifespan,
)


def _state(ctx: Context[ServerSession, AppState]) -> AppState:
    return ctx.request_context.lifespan_context


def _validate_value(
    value: str,
    *,
    name: str,
    max_length: int = 4096,
    allow_leading_dash: bool = False,
) -> str:
    if "\x00" in value or "\n" in value or "\r" in value:
        raise ToolError(f"{name} 不能包含 NUL 或换行")
    if len(value) > max_length:
        raise ToolError(f"{name} 长度不能超过 {max_length}")
    if not allow_leading_dash and value.startswith("-"):
        raise ToolError(f"{name} 不能以 '-' 开头")
    return value


def _optional_value(
    value: str | None,
    *,
    name: str,
    max_length: int,
    allow_leading_dash: bool = True,
) -> str | None:
    if value is None or not value.strip():
        return None
    return _validate_value(
        value.strip(),
        name=name,
        max_length=max_length,
        allow_leading_dash=allow_leading_dash,
    )


def _safe_scan_path(raw: str | None, settings: Settings) -> str | None:
    if raw is None or not raw.strip():
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = settings.repo_root / candidate
    resolved = candidate.resolve()
    try:
        relative = resolved.relative_to(settings.repo_root)
    except ValueError as exc:
        raise ToolError(f"scan path 必须位于仓库内：{settings.repo_root}") from exc
    if not resolved.exists():
        raise ToolError(f"scan path 不存在：{relative.as_posix()}")
    return "." if relative == Path(".") else relative.as_posix()


def _redact(args: Sequence[str]) -> list[str]:
    result: list[str] = []
    redact_next = False
    for arg in args:
        if redact_next:
            result.append("<redacted>")
            redact_next = False
        else:
            result.append(arg)
            redact_next = arg == "-background"
    return result


async def _capture(stream: asyncio.StreamReader | None, limit: int) -> _Captured:
    capture = _BoundedCapture(limit)
    if stream is None:
        return capture.finish()
    while chunk := await stream.read(64 * 1024):
        capture.feed(chunk)
    return capture.finish()


async def _terminate_tree(proc: asyncio.subprocess.Process, grace: float) -> None:
    if proc.returncode is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=grace)
        return
    except TimeoutError:
        pass
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except ProcessLookupError:
        pass
    await proc.wait()


def _error_excerpt(stdout: str, stderr: str, limit: int = 12_000) -> str:
    text = stderr.strip() or stdout.strip() or "(no output)"
    return text if len(text) <= limit else text[:limit] + "\n...[错误信息已截断]"


async def _ctx_log(
    ctx: Context[ServerSession, AppState],
    level: Literal["debug", "info", "warning", "error"],
    message: str,
) -> None:
    try:
        await getattr(ctx, level)(message)
    except Exception:  # best effort; clients may not support notifications
        logger.debug("context log failed", exc_info=True)


async def _progress(ctx: Context[ServerSession, AppState], progress: float, message: str) -> None:
    try:
        await ctx.report_progress(progress=progress, total=1.0, message=message)
    except Exception:
        logger.debug("progress notification failed", exc_info=True)


async def _run_ocr(
    ctx: Context[ServerSession, AppState],
    operation: str,
    *args: str,
    timeout: int,
) -> OCRCommandResult:
    state = _state(ctx)
    settings = state.settings
    command = [str(settings.ocr_bin), *args]
    display_args = _redact(args)
    started = time.monotonic()

    await _ctx_log(ctx, "info", f"开始 OCR 操作：{operation}")
    await _progress(ctx, 0.0, f"{operation}: waiting")

    async with state.process_slots:
        await _progress(ctx, 0.05, f"{operation}: starting")
        kwargs: dict[str, object] = {
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "cwd": str(settings.repo_root),
            "env": {
                **os.environ,
                "CI": os.environ.get("CI", "true"),
                "NO_COLOR": os.environ.get("NO_COLOR", "1"),
                "TERM": os.environ.get("TERM", "dumb"),
            },
        }
        if os.name == "posix":
            kwargs["start_new_session"] = True
        elif os.name == "nt":
            kwargs["creationflags"] = 0x00000200  # CREATE_NEW_PROCESS_GROUP

        try:
            proc = await asyncio.create_subprocess_exec(*command, **kwargs)
        except (FileNotFoundError, PermissionError, OSError) as exc:
            raise ToolError(f"无法启动 OCR：{exc}") from exc

        stdout_task = asyncio.create_task(_capture(proc.stdout, settings.max_output_bytes))
        stderr_task = asyncio.create_task(_capture(proc.stderr, settings.max_output_bytes))
        timed_out = False
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except TimeoutError:
            timed_out = True
            await _terminate_tree(proc, settings.terminate_grace_seconds)
        except asyncio.CancelledError:
            await _terminate_tree(proc, settings.terminate_grace_seconds)
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise

        stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
        duration_ms = round((time.monotonic() - started) * 1000)

        if timed_out:
            raise ToolError(
                f"OCR 操作 {operation!r} 在 {timeout}s 后超时，进程已终止。\n"
                f"{_error_excerpt(stdout.text, stderr.text)}"
            )
        exit_code = proc.returncode if proc.returncode is not None else -1
        if exit_code != 0:
            raise ToolError(
                f"OCR 操作 {operation!r} 失败，exit={exit_code}，耗时={duration_ms}ms。\n"
                f"{_error_excerpt(stdout.text, stderr.text)}"
            )

        await _progress(ctx, 1.0, f"{operation}: completed")
        await _ctx_log(ctx, "info", f"OCR 操作完成：{operation}（{duration_ms}ms）")
        return OCRCommandResult(
            operation=operation,
            command=display_args,
            exit_code=exit_code,
            duration_ms=duration_ms,
            stdout=stdout.text.strip() or "(no output)",
            stderr=stderr.text.strip(),
            stdout_truncated=stdout.truncated,
            stderr_truncated=stderr.truncated,
        )


@mcp.tool()
async def server_info(ctx: Context[ServerSession, AppState]) -> ServerInfo:
    """查看服务配置和仓库状态，不调用 OCR LLM。"""
    settings = _state(ctx).settings
    return ServerInfo(
        server_name=SERVER_NAME,
        ocr_bin=str(settings.ocr_bin),
        repo_root=str(settings.repo_root),
        repo_is_git_worktree=(settings.repo_root / ".git").exists(),
        max_processes=settings.max_processes,
        max_output_bytes=settings.max_output_bytes,
        python_version=sys.version.split()[0],
        platform=sys.platform,
    )


@mcp.tool()
async def review(
    ctx: Context[ServerSession, AppState],
    from_ref: Annotated[str, Field(description="起始 Git ref")] = "main",
    to_ref: Annotated[str, Field(description="目标 Git ref")] = "HEAD",
    model: Annotated[str | None, Field(description="覆盖 OCR 默认模型")] = None,
    exclude: Annotated[str | None, Field(description="逗号分隔的排除模式")] = None,
    background: Annotated[str | None, Field(description="需求背景或审查重点")] = None,
    format: Annotated[OutputFormat, Field(description="OCR 输出格式")] = "text",
    concurrency: Annotated[int, Field(ge=1, le=32)] = 8,
    preview: Annotated[bool, Field(description="只预览范围，不调用 LLM")] = False,
    timeout_seconds: Annotated[int, Field(ge=30, le=3600)] = 600,
) -> OCRCommandResult:
    """审查两个 Git ref 之间的差异。"""
    from_ref = _validate_value(from_ref, name="from_ref", max_length=512)
    to_ref = _validate_value(to_ref, name="to_ref", max_length=512)
    model = _optional_value(model, name="model", max_length=512)
    exclude = _optional_value(exclude, name="exclude", max_length=8192)
    background = _optional_value(background, name="background", max_length=50_000)
    args = [
        "review",
        "-from",
        from_ref,
        "-to",
        to_ref,
        "-format",
        format,
        "-concurrency",
        str(concurrency),
    ]
    if model:
        args += ["-model", model]
    if exclude:
        args += ["-exclude", exclude]
    if background:
        args += ["-background", background]
    if preview:
        args.append("-preview")
    return await _run_ocr(ctx, "review", *args, timeout=timeout_seconds)


@mcp.tool()
async def review_commit(
    ctx: Context[ServerSession, AppState],
    commit: Annotated[str, Field(description="commit hash 或 ref")] = "HEAD",
    model: Annotated[str | None, Field(description="覆盖 OCR 默认模型")] = None,
    exclude: Annotated[str | None, Field(description="逗号分隔的排除模式")] = None,
    background: Annotated[str | None, Field(description="需求背景或审查重点")] = None,
    format: Annotated[OutputFormat, Field(description="OCR 输出格式")] = "text",
    preview: Annotated[bool, Field(description="只预览范围，不调用 LLM")] = False,
    timeout_seconds: Annotated[int, Field(ge=30, le=3600)] = 600,
) -> OCRCommandResult:
    """审查单个 commit 的改动。"""
    commit = _validate_value(commit, name="commit", max_length=512)
    model = _optional_value(model, name="model", max_length=512)
    exclude = _optional_value(exclude, name="exclude", max_length=8192)
    background = _optional_value(background, name="background", max_length=50_000)
    args = ["review", "-commit", commit, "-format", format]
    if model:
        args += ["-model", model]
    if exclude:
        args += ["-exclude", exclude]
    if background:
        args += ["-background", background]
    if preview:
        args.append("-preview")
    return await _run_ocr(ctx, "review_commit", *args, timeout=timeout_seconds)


@mcp.tool()
async def scan(
    ctx: Context[ServerSession, AppState],
    path: Annotated[str | None, Field(description="仓库内文件或目录")] = None,
    model: Annotated[str | None, Field(description="覆盖 OCR 默认模型")] = None,
    exclude: Annotated[str | None, Field(description="逗号分隔的排除模式")] = None,
    format: Annotated[OutputFormat, Field(description="OCR 输出格式")] = "text",
    timeout_seconds: Annotated[int, Field(ge=30, le=3600)] = 600,
) -> OCRCommandResult:
    """扫描仓库内文件或目录；path 不能逃逸仓库根目录。"""
    safe_path = _safe_scan_path(path, _state(ctx).settings)
    model = _optional_value(model, name="model", max_length=512)
    exclude = _optional_value(exclude, name="exclude", max_length=8192)
    args = ["scan", "-format", format]
    if safe_path:
        args += ["--path", safe_path]
    if model:
        args += ["-model", model]
    if exclude:
        args += ["-exclude", exclude]
    return await _run_ocr(ctx, "scan", *args, timeout=timeout_seconds)


@mcp.tool()
async def delegate(
    ctx: Context[ServerSession, AppState],
    from_ref: Annotated[str, Field(description="起始 Git ref")] = "main",
    to_ref: Annotated[str, Field(description="目标 Git ref")] = "HEAD",
    timeout_seconds: Annotated[int, Field(ge=5, le=300)] = 30,
) -> OCRCommandResult:
    """输出 review spec，不调用 OCR 内部 LLM。"""
    from_ref = _validate_value(from_ref, name="from_ref", max_length=512)
    to_ref = _validate_value(to_ref, name="to_ref", max_length=512)
    return await _run_ocr(
        ctx,
        "delegate",
        "delegate",
        "-from",
        from_ref,
        "-to",
        to_ref,
        timeout=timeout_seconds,
    )


@mcp.tool()
async def sessions(
    ctx: Context[ServerSession, AppState],
    action: Annotated[SessionAction, Field(description="list 或 show")] = "list",
    session_id: Annotated[str | None, Field(description="show 时必填")] = None,
    timeout_seconds: Annotated[int, Field(ge=5, le=300)] = 30,
) -> OCRCommandResult:
    """列出或查看历史 review 会话。"""
    if action == "show":
        if not session_id or not session_id.strip():
            raise ToolError("action='show' 时必须提供 session_id")
        sid = _validate_value(session_id.strip(), name="session_id", max_length=512)
        args = ["session", "show", sid]
    else:
        if session_id:
            raise ToolError("action='list' 时不要提供 session_id")
        args = ["session", "list"]
    return await _run_ocr(ctx, f"sessions_{action}", *args, timeout=timeout_seconds)


@mcp.tool()
async def rules(
    ctx: Context[ServerSession, AppState],
    action: Annotated[RulesAction, Field(description="list 或 check")] = "list",
    timeout_seconds: Annotated[int, Field(ge=5, le=300)] = 30,
) -> OCRCommandResult:
    """列出规则或检查规则配置。"""
    return await _run_ocr(ctx, f"rules_{action}", "rules", action, timeout=timeout_seconds)


@mcp.tool()
async def llm_test(
    ctx: Context[ServerSession, AppState],
    timeout_seconds: Annotated[int, Field(ge=5, le=300)] = 30,
) -> OCRCommandResult:
    """测试 OCR 的 LLM 连接。"""
    return await _run_ocr(ctx, "llm_test", "llm", "test", timeout=timeout_seconds)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
