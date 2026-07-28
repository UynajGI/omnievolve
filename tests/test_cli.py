"""cli.py 集成测试 — typer CliRunner 命令验证."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from omnievolve.cli import (
    _apply_llm_env_overrides,
    _apply_setting_overrides,
    _load_project_snapshot,
    app,
)
from omnievolve.config import OmniEvolveSettings

pytestmark = pytest.mark.unit

runner = CliRunner()


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
