"""cli.py 集成测试 — typer CliRunner 命令验证."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from omnievolve.cli import app

pytestmark = pytest.mark.unit

runner = CliRunner()


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
        # 空实验导出空图，不应崩溃
        assert result.exit_code == 0

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
        # 空实验没有策略表，不应崩溃
        assert result.exit_code == 0


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
        # dry-run 扫描空 DB 应该成功
        assert result.exit_code == 0
