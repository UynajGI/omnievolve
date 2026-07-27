"""End-to-end CLI journey against both CodeStore backends."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from omnievolve.cli import app

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("backend", ["cas", "git"])
def test_sort_cli_journey(tmp_path: Path, backend: str, monkeypatch):
    def unavailable_embedder(*args, **kwargs):
        raise RuntimeError("disabled in CLI journey test")

    monkeypatch.setattr(
        "omnievolve.utils.embedding.SentenceTransformerEmbedder",
        unavailable_embedder,
    )

    root = tmp_path / backend
    db_path = root / "sort.db"
    config_path = root / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "\n".join(
            [
                "[evolution]",
                "max_generations = 1",
                "population_size = 1",
                "island_count = 1",
                "novelty_retry_limit = 0",
                "crossover_rate = 0.0",
                "self_evolve_enabled = false",
                "",
                "[models]",
                'heavy = ["fake"]',
                'light = ["fake"]',
                "max_tokens = 1024",
                "",
                "[novelty]",
                "embedding_gate = false",
                "ast_gate = true",
                "llm_judge_on_borderline = false",
                "",
                "[sandbox]",
                'backend = "trusted_subprocess"',
                "timeout_sec = 30",
                "",
                "[storage]",
                f'db_path = "{db_path.as_posix()}"',
                f'artifact_dir = "{(root / "artifacts").as_posix()}"',
                f'vector_dir = "{(root / "vectors").as_posix()}"',
                f'export_dir = "{(root / "exports").as_posix()}"',
                f'code_backend = "{backend}"',
                f'git_repo_path = "{(root / "repos").as_posix()}"',
                f'git_worktree_dir = "{(root / "worktrees").as_posix()}"',
            ]
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    evaluator = "examples.python_optimization.evaluator:SortEvaluator"
    initial = Path("examples/python_optimization/initial_code.py").resolve()
    common = ["-c", str(config_path)]

    result = runner.invoke(
        app,
        [
            "run",
            str(initial),
            "-e",
            evaluator,
            *common,
            "--trusted",
            "--gens",
            "0",
            "--no-self-evolve",
        ],
    )
    assert result.exit_code == 0, result.stdout

    with sqlite3.connect(db_path) as conn:
        experiment_id = conn.execute("SELECT id FROM experiment").fetchone()[0]

    result = runner.invoke(app, ["status", experiment_id, *common])
    assert result.exit_code == 0, result.stdout
    assert "Candidates: 1" in result.stdout

    result = runner.invoke(app, ["best", experiment_id, "--code", *common])
    assert result.exit_code == 0, result.stdout
    assert "def sort(" in result.stdout

    result = runner.invoke(app, ["policy", experiment_id, *common])
    assert result.exit_code == 0, result.stdout

    audit_path = root / "reports" / "audit.json"
    result = runner.invoke(
        app,
        ["audit", experiment_id, "--full", "-o", str(audit_path), *common],
    )
    assert result.exit_code == 0, result.stdout
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["missing_artifacts"] == []
    assert len(audit["candidates"]) == 1

    for export_format in ("json", "graphml"):
        export_path = root / "exports" / f"graph.{export_format}"
        result = runner.invoke(
            app,
            [
                "export",
                experiment_id,
                "--format",
                export_format,
                "--output",
                str(export_path),
                *common,
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert export_path.exists()

    result = runner.invoke(app, ["recover", experiment_id, "--dry-run", *common])
    assert result.exit_code == 0, result.stdout
    result = runner.invoke(app, ["recover", experiment_id, "--apply", *common])
    assert result.exit_code == 0, result.stdout

    result = runner.invoke(
        app,
        [
            "run",
            "--resume",
            experiment_id,
            "-e",
            evaluator,
            *common,
            "--trusted",
            "--gens",
            "0",
            "--no-self-evolve",
        ],
    )
    assert result.exit_code == 0, result.stdout

    result = runner.invoke(app, ["migrate", "--dry-run", *common])
    assert result.exit_code == 0, result.stdout
