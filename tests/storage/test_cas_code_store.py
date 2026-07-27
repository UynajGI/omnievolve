"""Contract tests for the CAS CodeStore adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from omnievolve.storage.artifact_store import ArtifactStore
from omnievolve.storage.cas_code_store import CASCodeStore
from omnievolve.storage.code_store import CodeStore

pytestmark = pytest.mark.unit


@pytest.fixture
def cas_store(db, tmp_path: Path) -> CASCodeStore:
    root = tmp_path / "artifacts"
    return CASCodeStore(ArtifactStore(root, db), tmp_path / "worktrees")


def test_protocol_and_roundtrip(cas_store: CASCodeStore):
    assert isinstance(cas_store, CodeStore)
    assert cas_store.backend_name == "cas"

    code = "def sort(values):\n    return sorted(values)\n"
    ref = cas_store.store_snapshot(code, parents=["ignored"], message="ignored")

    assert cas_store.exists(ref)
    assert cas_store.load_snapshot(ref) == code
    assert cas_store.load(ref) == code.encode()
    assert cas_store.get_parents(ref) == []


def test_materialize_and_release(cas_store: CASCodeStore):
    ref = cas_store.store_snapshot("value = 42\n")
    handle = cas_store.materialize(ref)

    assert handle.backend_id == "cas"
    assert (handle.path / "main.py").read_text(encoding="utf-8") == "value = 42\n"

    cas_store.release(handle)
    assert not handle.path.exists()
    cas_store.release(handle)


def test_diff_and_degraded_operations(cas_store: CASCodeStore):
    parent = cas_store.store_snapshot("value = 1\n")
    child = cas_store.store_snapshot("value = 2\n")

    diff = cas_store.diff(parent, child)
    assert "-value = 1" in diff
    assert "+value = 2" in diff
    assert cas_store.merge([parent, child]) is None

    cas_store.checkpoint("generation-1", child)
    assert cas_store.list_checkpoints() == []
