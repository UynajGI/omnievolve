"""logging.py 单元测试 — StructuredFormatter + setup + ProvenanceLogger."""

from __future__ import annotations

import json
import logging
import sys

import pytest

from omnievolve.utils.logging import (
    ProvenanceLogger,
    StructuredFormatter,
    setup_logging,
    setup_structlog,
)

pytestmark = pytest.mark.unit


class TestStructuredFormatter:
    def test_format_produces_json(self):
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="x.py",
            lineno=1,
            msg="hello world",
            args=(),
            exc_info=None,
        )
        result = formatter.format(record)
        parsed = json.loads(result)
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "hello world"
        assert "timestamp" in parsed
        assert "module" in parsed

    def test_format_with_exception(self):
        formatter = StructuredFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="x.py",
                lineno=1,
                msg="oh no",
                args=(),
                exc_info=sys.exc_info(),
            )
        result = formatter.format(record)
        parsed = json.loads(result)
        assert "exception" in parsed

    def test_format_with_extra_fields(self):
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="x.py",
            lineno=1,
            msg="candidate",
            args=(),
            exc_info=None,
        )
        record.experiment_id = "exp-1"  # type: ignore[attr-defined]
        record.candidate_id = "cand-1"  # type: ignore[attr-defined]
        record.agent_role = "director"  # type: ignore[attr-defined]
        record.extra_data = {"key": "value"}  # type: ignore[attr-defined]
        result = formatter.format(record)
        parsed = json.loads(result)
        assert parsed["experiment_id"] == "exp-1"
        assert parsed["candidate_id"] == "cand-1"
        assert parsed["agent_role"] == "director"
        assert parsed["extra"] == {"key": "value"}


class TestSetupLogging:
    def test_structured_mode(self):
        setup_logging(level="WARNING", structured=True)
        root = logging.getLogger()
        assert root.level == logging.WARNING
        assert len(root.handlers) >= 1
        assert isinstance(root.handlers[0].formatter, StructuredFormatter)

    def test_unstructured_mode(self):
        setup_logging(level="DEBUG", structured=False)
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        assert not isinstance(root.handlers[0].formatter, StructuredFormatter)

    def test_with_log_file(self, tmp_path):
        logfile = tmp_path / "test.log"
        setup_logging(level="INFO", structured=True, log_file=str(logfile))
        logging.getLogger("test").info("file test")
        assert logfile.exists()
        content = logfile.read_text()
        assert "file test" in content


class TestSetupStructlog:
    def test_falls_back_to_standard_on_import_error(self):
        """structlog 已安装时直接测试；验证不抛异常."""
        # 清除 existing handlers 让 basicConfig 生效
        root = logging.getLogger()
        for h in root.handlers[:]:
            root.removeHandler(h)
        setup_structlog(level="ERROR")
        # structlog 路径使用 basicConfig，第一次调用后 root 有 handler
        assert len(root.handlers) >= 1


class TestProvenanceLogger:
    def test_log_candidate_creation(self, caplog):
        caplog.set_level(logging.INFO)
        pl = ProvenanceLogger()
        pl.log_candidate_creation(
            candidate_id="c1",
            experiment_id="e1",
            parents=["p1"],
            thought_id="t1",
            artifact_hash="abc",
            search_policy_id="sp1",
        )
        assert "Candidate created" in caplog.text

    def test_log_evaluation(self, caplog):
        caplog.set_level(logging.INFO)
        pl = ProvenanceLogger()
        pl.log_evaluation(
            candidate_id="c1",
            experiment_id="e1",
            evaluator_version_id="ev1",
            environment_version_id="env1",
            score=0.95,
            passed=True,
        )
        assert "Evaluation completed" in caplog.text

    def test_log_llm_call(self, caplog):
        caplog.set_level(logging.INFO)
        pl = ProvenanceLogger()
        pl.log_llm_call(
            experiment_id="e1",
            agent_role="director",
            model="gpt-4o",
            prompt_version_id="pv1",
            input_tokens=100,
            output_tokens=50,
        )
        assert "LLM call" in caplog.text

    def test_log_policy_change(self, caplog):
        caplog.set_level(logging.INFO)
        pl = ProvenanceLogger()
        pl.log_policy_change(
            experiment_id="e1",
            old_policy_id="old",
            new_policy_id="new",
            risk_level="L1",
            evidence={"roi": 0.05},
        )
        assert "Policy change" in caplog.text
