"""cli.py 集成测试 — typer CliRunner 命令验证."""

from __future__ import annotations

import os

import pytest
from typer.testing import CliRunner

from omnievolve.cli import (
    _apply_llm_env_overrides,
    _apply_setting_overrides,
    _load_environment_files,
    _load_project_snapshot,
    app,
)
from omnievolve.config import OmniEvolveSettings, load_settings

pytestmark = pytest.mark.unit

runner = CliRunner()


def test_environment_files_preserve_process_env_and_prefer_local(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "OMNIEVOLVE_TEST_EXPLICIT=repo\n"
        "OMNIEVOLVE_TEST_LAYER=repo\n"
        "OMNIEVOLVE_TEST_REPO_ONLY=repo\n",
        encoding="utf-8",
    )
    (tmp_path / ".local.env").write_text(
        "OMNIEVOLVE_TEST_EXPLICIT=local\nOMNIEVOLVE_TEST_LAYER=local\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OMNIEVOLVE_TEST_EXPLICIT", "process")
    monkeypatch.delenv("OMNIEVOLVE_TEST_LAYER", raising=False)
    monkeypatch.delenv("OMNIEVOLVE_TEST_REPO_ONLY", raising=False)

    _load_environment_files()

    assert os.environ["OMNIEVOLVE_TEST_EXPLICIT"] == "process"
    assert os.environ["OMNIEVOLVE_TEST_LAYER"] == "local"
    assert os.environ["OMNIEVOLVE_TEST_REPO_ONLY"] == "repo"


def test_llm_env_overrides(monkeypatch):
    settings = OmniEvolveSettings()
    monkeypatch.setenv("OMNIEVOLVE_LLM_MODEL", "openai/test-model")
    monkeypatch.setenv("OMNIEVOLVE_LLM_API_BASE", "https://example.test/v1")
    monkeypatch.setenv("OMNIEVOLVE_LLM_MAX_TOKENS", "2048")

    kwargs = _apply_llm_env_overrides(settings)

    assert settings.models.heavy == ["openai/test-model"]
    assert settings.models.light == ["openai/test-model"]
    assert settings.models.max_tokens == 2048
    assert kwargs["api_base"] == "https://example.test/v1"
    assert kwargs["default_max_tokens"] == 2048


def test_llm_env_overrides_falls_back_to_openai_key(monkeypatch):
    monkeypatch.delenv("OMNIEVOLVE_LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "provider-key")

    kwargs = _apply_llm_env_overrides(OmniEvolveSettings())

    assert kwargs["api_key"] == "provider-key"


def test_invalid_llm_max_tokens(monkeypatch):
    settings = OmniEvolveSettings()
    monkeypatch.setenv("OMNIEVOLVE_LLM_MAX_TOKENS", "many")

    with pytest.raises(ValueError, match="must be an integer"):
        _apply_llm_env_overrides(settings)


def test_load_project_snapshot_preserves_text_tree(tmp_path):
    (tmp_path / "main.py").write_bytes(b"from pkg import answer\n")
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_bytes(b"answer = 42\n")
    ignored = tmp_path / "__pycache__"
    ignored.mkdir()
    (ignored / "main.py").write_text("bad = True\n", encoding="utf-8")

    snapshot = _load_project_snapshot(tmp_path)

    assert snapshot == {
        "main.py": "from pkg import answer\n",
        "pkg/__init__.py": "answer = 42\n",
    }


def test_load_project_snapshot_requires_main(tmp_path):
    (tmp_path / "solver.py").write_text("pass\n", encoding="utf-8")

    with pytest.raises(ValueError, match="main.py"):
        _load_project_snapshot(tmp_path)


def test_apply_setting_overrides_supports_typed_nested_values():
    settings = OmniEvolveSettings()

    _apply_setting_overrides(
        settings,
        [
            "evolution.seed=7",
            "evolution.self_evolve_enabled=false",
            "selection.parent_selector=random",
        ],
    )

    assert settings.evolution.seed == 7
    assert settings.evolution.self_evolve_enabled is False
    assert settings.selection.parent_selector == "random"


def test_apply_setting_overrides_rejects_unknown_path():
    with pytest.raises(ValueError, match="Unknown setting path"):
        _apply_setting_overrides(OmniEvolveSettings(), ["evolution.unknown=1"])


# --------------------------------------------------------------------------- #
#  doctor
# --------------------------------------------------------------------------- #


class TestDoctor:
    def test_doctor_runs(self):
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "Python:" in result.stdout


# --------------------------------------------------------------------------- #
#  run — argument parsing
# --------------------------------------------------------------------------- #


class TestRun:
    def test_missing_required_args_shows_error(self):
        """缺少必填参数时给出错误提示."""
        result = runner.invoke(app, ["run"])
        # typer 返回非 0 且提示缺少参数
        assert result.exit_code != 0

    def test_missing_evaluator_flag(self):
        """缺少 -e 时提示."""
        result = runner.invoke(app, ["run", "print(1)"])
        assert result.exit_code != 0

    def test_invalid_task_file(self, tmp_path):
        """不存在的任务文件给出错误."""
        fake_toml = tmp_path / "dummy.toml"
        fake_toml.write_text("[evolution]\nmax_generations = 1\n")
        result = runner.invoke(
            app,
            [
                "run",
                str(tmp_path / "nonexistent.py"),
                "-e",
                "omnievolve.eval.demo_evaluator:PythonUnitTestEvaluator",
                "-c",
                str(fake_toml),
                "--trusted",
                "--gens",
                "1",
            ],
        )
        # 文件不存在时会作为 raw code 读入 → 应该是错误
        # 实际会尝试加载并可能因缺少 sandbox/db 初始化而失败
        assert result.exit_code != 0 or "Error" in result.stdout


# --------------------------------------------------------------------------- #
#  status — needs experiment
# --------------------------------------------------------------------------- #


class TestStatus:
    def test_nonexistent_experiment(self, tmp_path):
        fake_toml = tmp_path / "dummy.toml"
        fake_toml.write_text("[evolution]\nmax_generations = 1\n")
        result = runner.invoke(app, ["status", "nonexistent-id", "-c", str(fake_toml)])
        assert result.exit_code != 0


# --------------------------------------------------------------------------- #
#  best — needs experiment
# --------------------------------------------------------------------------- #


class TestBest:
    def test_nonexistent_experiment(self, tmp_path):
        fake_toml = tmp_path / "dummy.toml"
        fake_toml.write_text("[evolution]\nmax_generations = 1\n")
        result = runner.invoke(app, ["best", "nonexistent-id", "-c", str(fake_toml)])
        assert result.exit_code != 0


# --------------------------------------------------------------------------- #
#  export
# --------------------------------------------------------------------------- #


class TestExport:
    def test_nonexistent_experiment(self, tmp_path):
        fake_toml = tmp_path / "dummy.toml"
        fake_toml.write_text(
            '[evolution]\nmax_generations = 1\n[sandbox]\nbackend = "trusted_subprocess"\n'
        )
        out = tmp_path / "out.graphml"
        result = runner.invoke(
            app,
            ["export", "nonexistent-id", "-c", str(fake_toml), "-o", str(out)],
        )
        assert result.exit_code != 0

    def test_invalid_format(self, tmp_path):
        fake_toml = tmp_path / "dummy.toml"
        fake_toml.write_text("[evolution]\nmax_generations = 1\n")
        result = runner.invoke(
            app,
            ["export", "x", "-f", "yaml", "-c", str(fake_toml), "-o", str(tmp_path / "x.yaml")],
        )
        assert result.exit_code != 0


# --------------------------------------------------------------------------- #
#  policy
# --------------------------------------------------------------------------- #


class TestPolicy:
    def test_nonexistent_experiment(self, tmp_path):
        fake_toml = tmp_path / "dummy.toml"
        fake_toml.write_text(
            '[evolution]\nmax_generations = 1\n[sandbox]\nbackend = "trusted_subprocess"\n'
        )
        result = runner.invoke(app, ["policy", "nonexistent-id", "-c", str(fake_toml)])
        assert result.exit_code != 0


# --------------------------------------------------------------------------- #
#  audit
# --------------------------------------------------------------------------- #


class TestAudit:
    def test_nonexistent_experiment(self, tmp_path):
        fake_toml = tmp_path / "dummy.toml"
        fake_toml.write_text("[evolution]\nmax_generations = 1\n")
        result = runner.invoke(app, ["audit", "nonexistent-id", "-c", str(fake_toml)])
        assert result.exit_code != 0


# --------------------------------------------------------------------------- #
#  recover
# --------------------------------------------------------------------------- #


class TestRecover:
    def test_nonexistent_experiment_dry_run(self, tmp_path):
        fake_toml = tmp_path / "dummy.toml"
        fake_toml.write_text("[evolution]\nmax_generations = 1\n")
        result = runner.invoke(
            app, ["recover", "nonexistent-id", "--dry-run", "-c", str(fake_toml)]
        )
        assert result.exit_code != 0


# --------------------------------------------------------------------------- #
#  verifier 接线（P1: CLI → EvolutionEngine 生产路径）
# --------------------------------------------------------------------------- #


class TestVerifierWiring:
    def test_run_passes_verifier_settings_to_engine(self, tmp_path, monkeypatch):
        """[verifier] TOML 配置必须进入 EvolutionEngine（observer 启动路径）."""
        import omnievolve.cli as cli_module
        import omnievolve.engine.evolution_engine as ee_module

        toml = tmp_path / "omnievolve.toml"
        toml.write_text(
            "[storage]\n"
            f"db_path = '{tmp_path / 'run.db'}'\n"
            f"artifact_dir = '{tmp_path / 'artifacts'}'\n"
            "[evolution]\nmax_generations = 1\n"
            "[verifier]\nenabled = true\nmode = 'observer'\nmodel = 'verifier-model'\n",
            encoding="utf-8",
        )
        settings = load_settings(str(toml))

        from omnievolve.storage.artifact_store import ArtifactStore
        from omnievolve.storage.db import Database
        from omnievolve.storage.migrations import initialize_database

        db = Database(settings.storage.db_path)
        initialize_database(db)
        artifact_store = ArtifactStore(settings.storage.artifact_dir, db)

        class _FakeSandbox:
            environment_version_id = "fake-sandbox@cli-v1"

            def healthcheck(self) -> dict[str, str]:
                return {"status": "healthy"}

        sandbox = _FakeSandbox()

        def fake_bootstrap(config, *, trusted=False, settings_overrides=None):
            del config, trusted, settings_overrides
            return settings, db, artifact_store, sandbox

        class _FakeEvaluator:
            version_id = "fake-evaluator@cli-v1"

            def build_plan(self, candidate, context):
                del candidate, context
                return None

            def parse_result(self, result, context):
                del result, context
                return None

        def fake_load_evaluator(path):
            assert path == "dummy:evaluator"
            return _FakeEvaluator

        def fake_components(db_, settings_, sandbox_, llm_):
            del db_, settings_, sandbox_, llm_
            return {}

        captured: dict[str, object] = {}

        class _FakeEngine:
            def __init__(self, *args, **kwargs):
                del args
                captured.update(kwargs)

            def run(self, code, task):
                del code, task
                return _FakeResult()

            def resume(self, experiment_id):
                del experiment_id
                return _FakeResult()

        class _FakeResult:
            best_candidate_id = "cand-x"
            best_score = 0.5
            champion_policy_id = "policy-1"
            total_generations = 1
            total_candidates = 1
            total_tokens = 10
            total_cost_usd = 0.0
            cost_known = False

        monkeypatch.setattr(cli_module, "_bootstrap", fake_bootstrap)
        monkeypatch.setattr(cli_module, "load_evaluator", fake_load_evaluator)
        monkeypatch.setattr(cli_module, "_build_engine_components", fake_components)
        monkeypatch.setattr(ee_module, "EvolutionEngine", _FakeEngine)

        result = runner.invoke(
            app,
            [
                "run",
                "print(1)",
                "-e",
                "dummy:evaluator",
                "-c",
                str(toml),
                "--trusted",
                "--gens",
                "1",
            ],
        )
        assert result.exit_code == 0, result.output
        assert captured["verifier_settings"] is settings.verifier
        assert captured["verifier_settings"].enabled is True
        assert captured["verifier_settings"].model == "verifier-model"

    def test_run_disables_verifier_by_default(self, tmp_path, monkeypatch):
        """未配置 [verifier] 时默认关闭（enabled=False）."""
        import omnievolve.cli as cli_module
        import omnievolve.engine.evolution_engine as ee_module

        toml = tmp_path / "omnievolve.toml"
        toml.write_text(
            "[storage]\n"
            f"db_path = '{tmp_path / 'run.db'}'\n"
            f"artifact_dir = '{tmp_path / 'artifacts'}'\n"
            "[evolution]\nmax_generations = 1\n",
            encoding="utf-8",
        )
        from omnievolve.config import load_settings

        settings = load_settings(str(toml))

        from omnievolve.storage.artifact_store import ArtifactStore
        from omnievolve.storage.db import Database
        from omnievolve.storage.migrations import initialize_database

        db = Database(settings.storage.db_path)
        initialize_database(db)
        artifact_store = ArtifactStore(settings.storage.artifact_dir, db)

        class _FakeSandbox:
            environment_version_id = "fake-sandbox@cli-v1"

            def healthcheck(self) -> dict[str, str]:
                return {"status": "healthy"}

        sandbox = _FakeSandbox()

        def fake_bootstrap(config, *, trusted=False, settings_overrides=None):
            del config, trusted, settings_overrides
            return settings, db, artifact_store, sandbox

        class _FakeEvaluator:
            version_id = "fake-evaluator@cli-v1"

            def build_plan(self, candidate, context):
                del candidate, context
                return None

            def parse_result(self, result, context):
                del result, context
                return None

        monkeypatch.setattr(cli_module, "_bootstrap", fake_bootstrap)
        monkeypatch.setattr(cli_module, "load_evaluator", lambda path: _FakeEvaluator)
        monkeypatch.setattr(cli_module, "_build_engine_components", lambda *a, **k: {})
        captured: dict[str, object] = {}

        class _FakeEngine:
            def __init__(self, *args, **kwargs):
                del args
                captured.update(kwargs)

            def run(self, code, task):
                del code, task
                return _FakeResult()

        class _FakeResult:
            best_candidate_id = "cand-x"
            best_score = 0.5
            champion_policy_id = "policy-1"
            total_generations = 1
            total_candidates = 1
            total_tokens = 10
            total_cost_usd = 0.0
            cost_known = False

        monkeypatch.setattr(ee_module, "EvolutionEngine", _FakeEngine)
        result = runner.invoke(
            app,
            ["run", "print(1)", "-e", "dummy:evaluator", "-c", str(toml), "--trusted"],
        )
        assert result.exit_code == 0, result.output
        assert captured["verifier_settings"].enabled is False
