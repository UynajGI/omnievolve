"""plan_validator.py 单元测试 — EvaluationPlan 校验 + Progressive Evaluation."""

from __future__ import annotations

import pytest

from omnievolve.eval.plan_validator import (
    EvaluationPlanValidator,
    EvaluationStage,
    PlanValidationError,
    ProgressiveEvaluationSpec,
    ResultParser,
    build_progressive_plan,
)
from omnievolve.sandbox.base import CommandSpec, EvaluationPlan, MountSpec

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
#  Test helpers
# --------------------------------------------------------------------------- #


def _safe_plan(**kwargs) -> EvaluationPlan:
    defaults = {
        "commands": [CommandSpec(argv=["python", "main.py"], timeout_sec=10.0)],
        "mounts": [],
        "expected_outputs": [],
        "network_access": False,
    }
    defaults.update(kwargs)
    return EvaluationPlan(**defaults)


# --------------------------------------------------------------------------- #
#  EvaluationStage
# --------------------------------------------------------------------------- #


class TestEvaluationStage:
    def test_all_stages_have_timeout_factor(self):
        for stage in EvaluationStage:
            assert stage.timeout_factor > 0

    def test_timeout_factors_are_monotonic(self):
        factors = [s.timeout_factor for s in EvaluationStage]
        assert factors == sorted(factors)

    def test_stage_descriptions_are_nonempty(self):
        for stage in EvaluationStage:
            assert len(stage.description) > 10

    def test_stage_0_is_shortest(self):
        assert EvaluationStage.STAGE_0_STATIC.timeout_factor == 0.1

    def test_stage_3_is_longest(self):
        assert EvaluationStage.STAGE_3_BENCHMARK.timeout_factor == 3.0


class TestProgressiveEvaluationSpec:
    def test_default_stages_are_all_four(self):
        spec = ProgressiveEvaluationSpec()
        assert len(spec.stages) == 4

    def test_early_exit_on_failure_defaults_true(self):
        spec = ProgressiveEvaluationSpec()
        assert spec.early_exit_on_failure is True

    def test_promotion_thresholds_exist(self):
        spec = ProgressiveEvaluationSpec()
        assert spec.promotion_threshold[0] == 1.0
        assert spec.promotion_threshold[1] == 0.8
        assert spec.promotion_threshold[2] == 0.95

    def test_custom_stages(self):
        spec = ProgressiveEvaluationSpec(
            stages=[EvaluationStage.STAGE_0_STATIC, EvaluationStage.STAGE_2_FULL_CORRECTNESS],
        )
        assert len(spec.stages) == 2


# --------------------------------------------------------------------------- #
#  EvaluationPlanValidator
# --------------------------------------------------------------------------- #


class TestEvaluationPlanValidator:
    def test_valid_plan_passes(self):
        validator = EvaluationPlanValidator()
        plan = _safe_plan()
        validator.validate(plan)  # 不应抛出异常

    def test_empty_commands_raises(self):
        validator = EvaluationPlanValidator()
        plan = _safe_plan(commands=[])
        with pytest.raises(PlanValidationError, match="No commands"):
            validator.validate(plan)

    def test_empty_argv_raises(self):
        validator = EvaluationPlanValidator()
        plan = _safe_plan(commands=[CommandSpec(argv=[], timeout_sec=5.0)])
        with pytest.raises(PlanValidationError, match="empty argv"):
            validator.validate(plan)

    def test_dangerous_pattern_rm_rf_raises(self):
        validator = EvaluationPlanValidator()
        plan = _safe_plan(commands=[CommandSpec(argv=["rm", "-rf", "/"], timeout_sec=5.0)])
        with pytest.raises(PlanValidationError, match="dangerous pattern"):
            validator.validate(plan)

    def test_dangerous_pattern_mkfs_raises(self):
        validator = EvaluationPlanValidator()
        plan = _safe_plan(commands=[CommandSpec(argv=["mkfs", "/dev/sda"], timeout_sec=5.0)])
        with pytest.raises(PlanValidationError, match="dangerous pattern"):
            validator.validate(plan)

    def test_dangerous_pattern_fork_bomb_raises(self):
        validator = EvaluationPlanValidator()
        plan = _safe_plan(
            commands=[CommandSpec(argv=["bash", "-c", ":(){ :|:& };:"], timeout_sec=5.0)]
        )
        with pytest.raises(PlanValidationError, match="dangerous pattern"):
            validator.validate(plan)

    def test_invalid_timeout_zero_raises(self):
        validator = EvaluationPlanValidator()
        plan = _safe_plan(commands=[CommandSpec(argv=["echo", "hi"], timeout_sec=0)])
        with pytest.raises(PlanValidationError, match="invalid timeout"):
            validator.validate(plan)

    def test_invalid_timeout_negative_raises(self):
        validator = EvaluationPlanValidator()
        plan = _safe_plan(commands=[CommandSpec(argv=["echo", "hi"], timeout_sec=-1)])
        with pytest.raises(PlanValidationError, match="invalid timeout"):
            validator.validate(plan)

    def test_path_traversal_in_mount_raises(self):
        validator = EvaluationPlanValidator()
        plan = _safe_plan(mounts=[MountSpec(source="../etc", target="/workspace/data")])
        with pytest.raises(PlanValidationError, match="path traversal"):
            validator.validate(plan)

    def test_path_traversal_in_target_raises(self):
        validator = EvaluationPlanValidator()
        plan = _safe_plan(mounts=[MountSpec(source="/data", target="../../../etc")])
        with pytest.raises(PlanValidationError, match="path traversal"):
            validator.validate(plan)

    def test_sensitive_mount_source_raises(self):
        validator = EvaluationPlanValidator()
        plan = _safe_plan(mounts=[MountSpec(source="/etc/secret", target="/workspace/secret")])
        with pytest.raises(PlanValidationError, match="sensitive"):
            validator.validate(plan)

    def test_safe_mount_passes(self):
        validator = EvaluationPlanValidator()
        plan = _safe_plan(mounts=[MountSpec(source="/home/user/data", target="/workspace/data")])
        validator.validate(plan)  # 不应抛出异常

    def test_multiple_commands_valid(self):
        validator = EvaluationPlanValidator()
        plan = _safe_plan(
            commands=[
                CommandSpec(argv=["python", "--version"], timeout_sec=5.0),
                CommandSpec(argv=["python", "main.py"], timeout_sec=30.0),
            ]
        )
        validator.validate(plan)

    def test_chmod_777_detected(self):
        validator = EvaluationPlanValidator()
        plan = _safe_plan(commands=[CommandSpec(argv=["chmod", "777", "/tmp/x"], timeout_sec=5.0)])
        with pytest.raises(PlanValidationError, match="dangerous pattern"):
            validator.validate(plan)


# --------------------------------------------------------------------------- #
#  ResultParser
# --------------------------------------------------------------------------- #


class TestResultParser:
    def test_timeout_identified(self):
        parser = ResultParser()
        result = parser.classify_error([-1], "", timed_out=True)
        assert result == "timeout"

    def test_segfault_identified(self):
        parser = ResultParser()
        result = parser.classify_error([-11], "Segmentation fault", timed_out=False)
        assert result == "crash"

    def test_sigsegv_in_stderr(self):
        parser = ResultParser()
        result = parser.classify_error([0], "SIGSEGV at 0x004", timed_out=False)
        assert result == "crash"

    def test_killed_identified(self):
        parser = ResultParser()
        result = parser.classify_error([0], "Killed", timed_out=False)
        assert result == "crash"

    def test_syntax_error_identified(self):
        parser = ResultParser()
        result = parser.classify_error([1], "SyntaxError: invalid syntax", timed_out=False)
        assert result == "syntax_error"

    def test_import_error_identified(self):
        parser = ResultParser()
        result = parser.classify_error(
            [1], "ModuleNotFoundError: No module named 'foo'", timed_out=False
        )
        assert result == "import_error"

    def test_importerror_identified(self):
        parser = ResultParser()
        result = parser.classify_error([1], "ImportError: cannot import name", timed_out=False)
        assert result == "import_error"

    def test_compilation_error_identified(self):
        parser = ResultParser()
        result = parser.classify_error([1], "compilation error at line 5", timed_out=False)
        assert result == "compilation_error"

    def test_assertion_error_identified(self):
        parser = ResultParser()
        result = parser.classify_error([1], "AssertionError: x != y", timed_out=False)
        assert result == "assertion_error"

    def test_runtime_error_identified(self):
        parser = ResultParser()
        result = parser.classify_error([1], "RuntimeError: something went wrong", timed_out=False)
        assert result == "runtime_error"

    def test_sigsegv_exit_code(self):
        parser = ResultParser()
        result = parser.classify_error([-11], "", timed_out=False)
        assert result == "crash"

    def test_sigkill_exit_code(self):
        parser = ResultParser()
        result = parser.classify_error([-9], "", timed_out=False)
        assert result == "crash"

    def test_unknown_fallback(self):
        parser = ResultParser()
        result = parser.classify_error([1], "some random error", timed_out=False)
        assert result == "unknown"

    def test_timeout_is_retriable(self):
        parser = ResultParser()
        assert parser.is_retriable("timeout") is True

    def test_unknown_is_retriable(self):
        parser = ResultParser()
        assert parser.is_retriable("unknown") is True

    def test_crash_is_not_retriable(self):
        parser = ResultParser()
        assert parser.is_retriable("crash") is False

    def test_syntax_error_is_not_retriable(self):
        parser = ResultParser()
        assert parser.is_retriable("syntax_error") is False


# --------------------------------------------------------------------------- #
#  build_progressive_plan
# --------------------------------------------------------------------------- #


class TestBuildProgressivePlan:
    def test_stage_0_reduces_timeout(self):
        base = _safe_plan(commands=[CommandSpec(argv=["python", "main.py"], timeout_sec=10.0)])
        plan = build_progressive_plan(base, EvaluationStage.STAGE_0_STATIC)
        assert plan.commands[0].timeout_sec == pytest.approx(1.0)  # 10 * 0.1

    def test_stage_3_increases_timeout(self):
        base = _safe_plan(commands=[CommandSpec(argv=["python", "main.py"], timeout_sec=10.0)])
        plan = build_progressive_plan(base, EvaluationStage.STAGE_3_BENCHMARK)
        assert plan.commands[0].timeout_sec == pytest.approx(30.0)  # 10 * 3.0

    def test_resource_profile_reflects_stage(self):
        base = _safe_plan()
        plan = build_progressive_plan(base, EvaluationStage.STAGE_2_FULL_CORRECTNESS)
        assert "stage2" in plan.resource_profile

    def test_network_access_preserved(self):
        base = _safe_plan(network_access=True)
        plan = build_progressive_plan(base, EvaluationStage.STAGE_1_SMALL_SAMPLE)
        assert plan.network_access is True

    def test_mounts_preserved(self):
        base = _safe_plan(mounts=[MountSpec(source="/data", target="/workspace/data")])
        plan = build_progressive_plan(base, EvaluationStage.STAGE_0_STATIC)
        assert len(plan.mounts) == 1

    def test_multiple_commands_all_adjusted(self):
        base = _safe_plan(
            commands=[
                CommandSpec(argv=["cmd1"], timeout_sec=5.0),
                CommandSpec(argv=["cmd2"], timeout_sec=10.0),
            ]
        )
        plan = build_progressive_plan(base, EvaluationStage.STAGE_3_BENCHMARK)
        assert plan.commands[0].timeout_sec == pytest.approx(15.0)
        assert plan.commands[1].timeout_sec == pytest.approx(30.0)
