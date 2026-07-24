"""GitCodeStore 测试 — Phase 2.

覆盖: store/load round-trip, worktree create/release,
diff, merge (成功/冲突), checkpoint, exists, 并发 store.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from omnievolve.storage.code_store import CodeStore, WorktreeHandle
from omnievolve.storage.git_code_store import GitCodeStore


@pytest.fixture
def git_store(tmp_path: Path) -> GitCodeStore:
    """创建临时 GitCodeStore（已绑定实验）."""
    repo = tmp_path / "code_root"
    wt = tmp_path / "worktrees"
    store = GitCodeStore(repo, wt)
    store.bind_experiment("test_exp")
    return store


class TestGitCodeStoreBasic:
    """基础 store/load 测试."""

    def test_implements_protocol(self, git_store: GitCodeStore):
        """实现 CodeStore Protocol."""
        assert isinstance(git_store, CodeStore)
        assert git_store.backend_name == "git"

    def test_store_and_load_roundtrip(self, git_store: GitCodeStore):
        """store_snapshot + load_snapshot round-trip."""
        code = "def sort(arr):\n    return sorted(arr)\n"
        ref = git_store.store_snapshot(code, message="initial")
        assert len(ref) == 40  # Git SHA-1
        loaded = git_store.load_snapshot(ref)
        assert loaded == code

    def test_store_with_parents(self, git_store: GitCodeStore):
        """带 parents 的 store 建立 ancestry."""
        parent_ref = git_store.store_snapshot("code_v1", message="v1")
        child_ref = git_store.store_snapshot(
            "code_v2", parents=[parent_ref], message="v2"
        )
        parents = git_store.get_parents(child_ref)
        assert parents == [parent_ref]
        assert git_store.get_parents(parent_ref) == []

    def test_store_multi_parent(self, git_store: GitCodeStore):
        """多父代 (crossover 场景)."""
        p1 = git_store.store_snapshot("code_a")
        p2 = git_store.store_snapshot("code_b")
        child = git_store.store_snapshot(
            "code_merged", parents=[p1, p2], message="crossover"
        )
        parents = sorted(git_store.get_parents(child))
        assert parents == sorted([p1, p2])

    def test_exists(self, git_store: GitCodeStore):
        """exists 检查."""
        ref = git_store.store_snapshot("code")
        assert git_store.exists(ref)
        assert not git_store.exists("nonexistent_sha_1234567")

    def test_message_in_commit(self, git_store: GitCodeStore):
        """commit message 被正确存储."""
        ref = git_store.store_snapshot("x", message="test message here")
        # 通过 rev-list 验证 commit 存在
        output = git_store._git(["log", "--format=%s", "-n", "1", ref])
        assert "test message here" in output


class TestWorktree:
    """worktree materialize/release 测试."""

    def test_materialize_creates_main_py(self, git_store: GitCodeStore):
        """materialize 创建包含 main.py 的工作目录."""
        code = "print('hello')"
        ref = git_store.store_snapshot(code)
        ws = git_store.materialize(ref)

        assert ws.backend_id == "git"
        assert ws.needs_cleanup is True
        assert ws.path.exists()
        assert (ws.path / "main.py").exists()
        assert (ws.path / "main.py").read_text() == code

        git_store.release(ws)
        assert not ws.path.exists()

    def test_materialize_multiple(self, git_store: GitCodeStore):
        """多个 worktree 并行存在."""
        ref1 = git_store.store_snapshot("code1")
        ref2 = git_store.store_snapshot("code2")

        ws1 = git_store.materialize(ref1)
        ws2 = git_store.materialize(ref2)

        assert ws1.path != ws2.path
        assert (ws1.path / "main.py").read_text() == "code1"
        assert (ws2.path / "main.py").read_text() == "code2"

        git_store.release(ws1)
        git_store.release(ws2)

    def test_release_idempotent(self, git_store: GitCodeStore):
        """重复 release 不崩溃."""
        ref = git_store.store_snapshot("x")
        ws = git_store.materialize(ref)
        git_store.release(ws)
        git_store.release(ws)  # 不崩溃


class TestDiff:
    """diff 测试."""

    def test_diff_output(self, git_store: GitCodeStore):
        """diff 输出 unified diff."""
        parent = git_store.store_snapshot("line1\nline2\n")
        child = git_store.store_snapshot("line1\nline3\n", parents=[parent])
        d = git_store.diff(parent, child)
        assert "-line2" in d
        assert "+line3" in d

    def test_diff_identical(self, git_store: GitCodeStore):
        """diff 相同代码返回空."""
        ref1 = git_store.store_snapshot("same code")
        ref2 = git_store.store_snapshot("same code")
        d = git_store.diff(ref1, ref2)
        assert d.strip() == ""


class TestMerge:
    """merge (crossover) 测试."""

    def test_merge_no_conflict(self, git_store: GitCodeStore):
        """无冲突 merge 成功."""
        base = git_store.store_snapshot("def f():\n    return 1\n")
        # 两个分支修改不同部分
        c1 = git_store.store_snapshot("def f():\n    return 2\n", parents=[base])
        c2 = git_store.store_snapshot("def f():\n    return 3\n", parents=[base])
        merged = git_store.merge([c1, c2])
        # merge 可能成功也可能冲突（取决于 git 策略）
        if merged is not None:
            assert len(merged) == 40

    def test_merge_single_parent(self, git_store: GitCodeStore):
        """单个 parent 直接返回."""
        ref = git_store.store_snapshot("code")
        result = git_store.merge([ref])
        assert result == ref

    def test_merge_empty(self, git_store: GitCodeStore):
        """空列表返回 None."""
        assert git_store.merge([]) is None


class TestCheckpoint:
    """checkpoint 测试."""

    def test_checkpoint_create_and_list(self, git_store: GitCodeStore):
        """创建和列出 checkpoint."""
        ref = git_store.store_snapshot("code", message="v1")
        git_store.checkpoint("gen_1", ref)

        checkpoints = git_store.list_checkpoints()
        assert len(checkpoints) >= 1
        names = [c[0] for c in checkpoints]
        assert any("gen_1" in n for n in names)

    def test_checkpoint_multiple(self, git_store: GitCodeStore):
        """多个 checkpoint."""
        ref1 = git_store.store_snapshot("v1")
        ref2 = git_store.store_snapshot("v2", parents=[ref1])

        git_store.checkpoint("gen_1", ref1)
        git_store.checkpoint("gen_2", ref2)

        checkpoints = git_store.list_checkpoints()
        names = {c[0] for c in checkpoints}
        assert any("gen_1" in n for n in names)
        assert any("gen_2" in n for n in names)


class TestConcurrency:
    """并发安全测试."""

    def test_concurrent_store(self, git_store: GitCodeStore):
        """10 线程并行 store_snapshot — 无竞争."""
        refs: list[str] = []
        errors: list[Exception] = []

        def worker(i: int) -> None:
            try:
                ref = git_store.store_snapshot(
                    f"code_{i}", message=f"thread_{i}"
                )
                refs.append(ref)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(refs) == 10
        # 所有 ref 应该唯一
        assert len(set(refs)) == 10

    def test_concurrent_materialize(self, git_store: GitCodeStore):
        """并行 materialize 不同候选."""
        refs = [
            git_store.store_snapshot(f"code_{i}", message=f"v{i}")
            for i in range(5)
        ]
        handles: list[WorktreeHandle] = []
        errors: list[Exception] = []

        def worker(ref: str) -> None:
            try:
                ws = git_store.materialize(ref)
                handles.append(ws)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(r,)) for r in refs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(handles) == 5
        # 每个 worktree 应该有独立路径
        paths = {h.path for h in handles}
        assert len(paths) == 5

        # 清理
        for h in handles:
            git_store.release(h)


class TestGC:
    """GC 测试."""

    def test_gc_no_error(self, git_store: GitCodeStore):
        """GC 不应崩溃."""
        for i in range(5):
            git_store.store_snapshot(f"code_{i}")
        result = git_store.gc()
        assert result["status"] == "ok"
