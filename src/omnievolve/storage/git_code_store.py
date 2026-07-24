"""Git 原生代码存储后端.

设计文档 §2: 每个候选 = Git commit，ancestry = 血缘。
worktree = 零拷贝沙箱隔离，merge = crossover，ref = checkpoint。

Phase 2: GitCodeStore 核心实现

核心设计:
- 使用 subprocess 调用 git CLI（不引入 GitPython 依赖）
- 使用 plumbing 命令 (hash-object/mktree/commit-tree) 保证多线程并行安全
- bare repo 存储所有对象，worktree 做沙箱物化

线程安全:
- store_snapshot: plumbing 命令不触碰 index 文件 → 多线程并行安全
- materialize/release: 操作不同路径 → 天然并行安全
- gc: 使用 threading.Lock() 串行化
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any

from omnievolve.storage.code_store import WorktreeHandle

logger = logging.getLogger(__name__)

# 固定作者信息（避免环境变量泄漏）
_GIT_ENV = {
    "GIT_AUTHOR_NAME": "OmniEvolve",
    "GIT_AUTHOR_EMAIL": "bot@omnievolve.local",
    "GIT_COMMITTER_NAME": "OmniEvolve",
    "GIT_COMMITTER_EMAIL": "bot@omnievolve.local",
}


class GitCodeStore:
    """Git 原生代码存储后端.

    - store_snapshot: hash-object + mktree + commit-tree → commit SHA
    - load_snapshot: cat-file blob <sha>
    - materialize: git worktree add --detach <path> <sha>
    - diff: git diff <parent>..<child>
    - merge: worktree 中 git merge → crossover
    - checkpoint: update-ref refs/checkpoints/<name> <sha>
    """

    def __init__(
        self,
        repo_path: str | Path,
        worktree_root: str | Path,
    ) -> None:
        """初始化 Git 后端.

        Args:
            repo_path: bare git 仓库路径
            worktree_root: worktree 工作目录根
        """
        self._repo_path = Path(repo_path)
        self._wt_root = Path(worktree_root)
        self._wt_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()  # 仅保护 gc 等全局操作
        self._init_repo()

    @property
    def backend_name(self) -> str:
        """后端名称."""
        return "git"

    # ─── 内部工具 ──────────────────────────────────────────

    def _git(
        self,
        args: list[str],
        *,
        input_data: str | bytes | None = None,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> str:
        """执行 git 命令（通过 --git-dir 指向 bare repo）.

        所有 git 调用集中在此方法，便于审计和 mock。
        """
        full_env = {**os.environ, **_GIT_ENV, **(env or {})}
        result = subprocess.run(
            ["git", "--git-dir", str(self._repo_path)] + args,
            input=input_data,
            capture_output=True,
            text=True,
            env=full_env,
        )
        if check and result.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} failed: {result.stderr.strip()}"
            )
        return result.stdout.strip()

    def _git_in_worktree(
        self,
        wt_path: Path,
        args: list[str],
        *,
        input_data: str | bytes | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """在 worktree 目录中执行 git 命令."""
        result = subprocess.run(
            ["git", "-C", str(wt_path)] + args,
            input=input_data,
            capture_output=True,
            text=True,
            env={**os.environ, **_GIT_ENV},
        )
        if check and result.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} failed in {wt_path}: {result.stderr.strip()}"
            )
        return result

    def _init_repo(self) -> None:
        """初始化 bare git repo（如果不存在）."""
        if not (self._repo_path / "HEAD").exists():
            self._repo_path.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "init", "--bare", str(self._repo_path)],
                capture_output=True,
                check=True,
            )
            self._git(["config", "gc.auto", "256"])
            self._git(["config", "gc.reflogExpire", "never"])
            logger.info("Initialized bare git repo at %s", self._repo_path)

    # ─── CodeStore Protocol 实现 ──────────────────────────

    def store_snapshot(
        self,
        code: str,
        *,
        parents: list[str] | None = None,
        message: str = "",
        meta: dict[str, Any] | None = None,
    ) -> str:
        """存储代码快照 → 返回 commit SHA.

        使用 plumbing 命令保证线程安全:
        1. hash-object 写 blob
        2. mktree 构建树（单文件 main.py）
        3. commit-tree 创建 commit（parents = ancestry）

        plumbing 命令不触碰 index 文件，多线程并行调用安全。
        """
        # Step 1: 写 blob
        blob_sha = self._git(
            ["hash-object", "-w", "--stdin"],
            input_data=code,
        )

        # Step 2: 构建 tree（单文件 main.py = 候选代码）
        tree_entry = f"100644 blob {blob_sha}\tmain.py"
        tree_sha = self._git(["mktree"], input_data=tree_entry)

        # Step 3: 创建 commit（parents = ancestry）
        args = ["commit-tree", tree_sha]
        for p in parents or []:
            args += ["-p", p]

        msg = message or json.dumps(meta or {}, ensure_ascii=False)
        args += ["-m", msg]

        commit_sha = self._git(args)
        return commit_sha

    def load_snapshot(self, ref: str) -> str:
        """加载代码快照文本.

        通过 cat-file 读取 commit tree 中的 main.py blob。
        注意: 不使用 _git() 因为它会 strip() 输出。
        """
        # 获取 commit 的 tree
        tree_sha = self._git(["rev-parse", f"{ref}^{{tree}}"])
        # 从 tree 中获取 main.py 的 blob hash
        ls_line = self._git(["ls-tree", tree_sha, "main.py"])
        blob_sha = ls_line.split()[2]
        # 读取 blob 内容（不 strip，保留原始换行）
        result = subprocess.run(
            ["git", "--git-dir", str(self._repo_path), "cat-file", "blob", blob_sha],
            capture_output=True,
            env={**os.environ, **_GIT_ENV},
        )
        return result.stdout.decode("utf-8")

    def exists(self, ref: str) -> bool:
        """检查 ref 是否存在."""
        result = subprocess.run(
            ["git", "--git-dir", str(self._repo_path), "cat-file", "-e", ref],
            capture_output=True,
            env={**os.environ, **_GIT_ENV},
        )
        return result.returncode == 0

    def materialize(self, ref: str) -> WorktreeHandle:
        """创建 worktree — 零拷贝隔离环境.

        使用 --detach 避免创建分支（防止 ref 增长）。
        每个 worktree 路径含随机后缀，天然避免冲突。
        """
        wt_name = f"wt_{ref[:8]}_{uuid.uuid4().hex[:6]}"
        wt_path = self._wt_root / wt_name

        self._git(
            ["worktree", "add", "--detach", str(wt_path), ref],
        )

        return WorktreeHandle(
            path=wt_path,
            backend_id="git",
            needs_cleanup=True,
        )

    def release(self, handle: WorktreeHandle) -> None:
        """移除 worktree."""
        if handle.backend_id == "git" and handle.needs_cleanup:
            try:
                self._git(
                    ["worktree", "remove", "--force", str(handle.path)],
                    check=False,
                )
            except Exception:
                logger.debug(
                    "Worktree removal failed for %s",
                    handle.path,
                    exc_info=True,
                )

    def diff(self, parent_ref: str, child_ref: str) -> str:
        """返回 parent → child 的 unified diff."""
        return self._git(
            ["diff", "--no-color", parent_ref, child_ref, "--", "main.py"],
        )

    def get_parents(self, ref: str) -> list[str]:
        """获取 commit 的父代列表（Git ancestry）."""
        try:
            output = self._git(["rev-list", "--parents", "-n", "1", ref])
            parts = output.strip().split()
            # 第一项是 ref 本身，其余是 parents
            return parts[1:] if len(parts) > 1 else []
        except Exception:
            return []

    def merge(self, parent_refs: list[str]) -> str | None:
        """多父代 merge commit = crossover.

        在临时 worktree 中执行 merge。冲突时返回 None（触发 fallback）。
        """
        if len(parent_refs) < 2:
            return parent_refs[0] if parent_refs else None

        first = parent_refs[0]
        wt = self.materialize(first)
        try:
            for other in parent_refs[1:]:
                result = self._git_in_worktree(
                    wt.path,
                    ["merge", "--no-commit", "--no-ff", other],
                    check=False,
                )
                if result.returncode != 0:
                    # 冲突 → abort + 返回 None
                    self._git_in_worktree(
                        wt.path, ["merge", "--abort"], check=False
                    )
                    logger.debug(
                        "Git merge conflict between %s and %s",
                        first[:8],
                        other[:8],
                    )
                    return None

            # 获取 merge 后的 HEAD SHA
            merged_sha = self._git_in_worktree(
                wt.path, ["rev-parse", "HEAD"]
            ).stdout.strip()
            return merged_sha
        finally:
            self.release(wt)

    def checkpoint(self, name: str, ref: str) -> None:
        """创建命名检查点 ref."""
        ref_name = f"refs/checkpoints/{name}"
        self._git(["update-ref", ref_name, ref])
        logger.info("Checkpoint created: %s → %s", name, ref[:8])

    def list_checkpoints(self) -> list[tuple[str, str]]:
        """列出所有检查点."""
        try:
            output = self._git(
                ["for-each-ref", "--format=%(refname:short) %(objectname)",
                 "refs/checkpoints/"],
            )
            results = []
            for line in output.strip().split("\n"):
                if line:
                    parts = line.split()
                    if len(parts) == 2:
                        results.append((parts[0], parts[1]))
            return results
        except Exception:
            return []

    def gc(self) -> dict[str, str]:
        """垃圾回收 — 清理悬空 worktree + 过期 reflog + 压缩对象.

        在 AsyncPipelineEngine 的 Phase C（代间同步）中定期调用。
        """
        with self._lock:
            self._git(["worktree", "prune"], check=False)
            self._git(
                ["reflog", "expire", "--expire-unreachable=now", "--all"],
                check=False,
            )
            self._git(["gc", "--auto", "--prune=now"], check=False)
        logger.info("Git GC completed")
        return {"status": "ok"}
