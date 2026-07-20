"""新增模块测试：infra_adapter / audit / config_snapshot / plugins / LLM novelty judge."""

from __future__ import annotations

import json

import pytest

from omnievolve.engine.novelty import LLMNoveltyJudge, NoveltyDecision, NoveltyGate
from omnievolve.eval.environment import ExecutionEnvironmentVersion
from omnievolve.meta.audit import AuditReportGenerator
from omnievolve.meta.infra_adapter import (
    InfraAdaptation,
    InfraAdapter,
)
from omnievolve.meta.policy_archive import PolicyArchive
from omnievolve.meta.policy_genome import SearchPolicyGenome
from omnievolve.plugins.base import PluginRegistry
from omnievolve.plugins.geo import GeoPlugin
from omnievolve.plugins.quant import QuantPlugin
from omnievolve.storage.db import create_memory_database
from omnievolve.storage.migrations import initialize_database
from omnievolve.storage.repositories.candidate_repo import CandidateRepository
from omnievolve.storage.repositories.experiment_repo import ExperimentRepository
from omnievolve.utils.config_snapshot import (
    create_audit_snapshot,
    mask_env_vars,
    mask_secrets,
    mask_value,
    validate_config_snapshot,
)


@pytest.fixture
def db():
    database = create_memory_database()
    initialize_database(database)
    yield database
    database.close()


# --------------------------------------------------------------------------- #
#  InfraAdapter
# --------------------------------------------------------------------------- #


class TestInfraAdapter:
    def test_classify_l0_l1_l2(self, db):
        adapter = InfraAdapter(db)
        assert adapter.classify("log_format") == "L0"
        assert adapter.classify("timeout_schedule") == "L1"
        assert adapter.classify("task_semantics") == "L2"  # 未知 = 禁止

    def test_can_adapt_rejects_l2(self, db):
        adapter = InfraAdapter(db)
        ok, reason = adapter.can_adapt("task_semantics")
        assert not ok
        assert "L2" in reason

    def test_can_adapt_allows_l1(self, db):
        adapter = InfraAdapter(db)
        ok, _ = adapter.can_adapt("build_cache")
        assert ok

    def test_propose_creates_new_env_version(self, db):
        adapter = InfraAdapter(db)
        env = ExecutionEnvironmentVersion(
            id="env-base",
            backend="docker",
            resource_policy={},
        )
        adaptation = InfraAdaptation(
            field_name="timeout_schedule",
            old_value=30,
            new_value=60,
            rationale="slow tests need more time",
        )
        new_env = adapter.propose(env, adaptation)
        assert new_env is not None
        assert new_env.id != "env-base"
        assert "timeout_schedule" in new_env.resource_policy

    def test_propose_rejects_l2_field(self, db):
        adapter = InfraAdapter(db)
        env = ExecutionEnvironmentVersion(id="env-base", backend="docker")
        adaptation = InfraAdaptation(
            field_name="score_formula",
            old_value="mean",
            new_value="max",
        )
        result = adapter.propose(env, adaptation)
        assert result is None

    def test_validate_promotion_pass(self, db):
        adapter = InfraAdapter(db)
        ok, _ = adapter.validate_promotion(
            old_scores=[0.5, 0.6, 0.55],
            new_scores=[0.51, 0.61, 0.56],
            old_ranks=[1, 2, 3],
            new_ranks=[1, 2, 3],
        )
        assert ok

    def test_validate_promotion_rejects_drift(self, db):
        adapter = InfraAdapter(db, max_baseline_drift=0.01)
        ok, reason = adapter.validate_promotion(
            old_scores=[0.5],
            new_scores=[0.8],
            old_ranks=[1],
            new_ranks=[1],
        )
        assert not ok
        assert "drift" in reason.lower()

    def test_validate_promotion_rejects_rank_change(self, db):
        adapter = InfraAdapter(db, min_rank_correlation=0.99)
        ok, reason = adapter.validate_promotion(
            old_scores=[0.5, 0.6, 0.7],
            new_scores=[0.5, 0.6, 0.7],
            old_ranks=[1, 2, 3],
            new_ranks=[3, 2, 1],
        )
        assert not ok
        assert "rank" in reason.lower()


# --------------------------------------------------------------------------- #
#  Config Snapshot / Secret Masking
# --------------------------------------------------------------------------- #


class TestConfigSnapshot:
    def test_mask_value(self):
        assert mask_value("sk-abc123xyz") == "sk-a***"
        assert mask_value("ab") == "***"

    def test_mask_secrets_recursive(self):
        data = {
            "api_key": "sk-secret123",
            "model": "gpt-4o",
            "nested": {
                "token": "tok-abc",
                "safe_field": 42,
            },
            "list": [{"secret_key": "hidden"}, {"name": "visible"}],
        }
        masked = mask_secrets(data)
        assert masked["api_key"] == "sk-s***"
        assert masked["model"] == "gpt-4o"
        assert masked["nested"]["token"] == "tok-***"
        assert masked["nested"]["safe_field"] == 42
        assert masked["list"][0]["secret_key"] == "hidd***"
        assert masked["list"][1]["name"] == "visible"

    def test_mask_env_vars(self):
        env = {
            "OPENAI_API_KEY": "sk-secret",
            "HOME": "/home/user",
            "DATABASE_TOKEN": "tok-xyz",
            "PATH": "/usr/bin",
        }
        masked = mask_env_vars(env)
        assert "***" in masked["OPENAI_API_KEY"]
        assert masked["HOME"] == "/home/user"
        assert "***" in masked["DATABASE_TOKEN"]
        assert masked["PATH"] == "/usr/bin"

    def test_validate_config_snapshot_valid(self):
        snapshot = {
            "evolution": {"max_generations": 10, "population_size": 8},
            "sandbox": {"timeout_sec": 30, "backend": "docker"},
        }
        ok, errors = validate_config_snapshot(snapshot)
        assert ok, errors

    def test_validate_config_snapshot_missing_section(self):
        ok, errors = validate_config_snapshot({})
        assert not ok
        assert any("evolution" in e for e in errors)

    def test_validate_config_snapshot_invalid_backend(self):
        snapshot = {
            "evolution": {"max_generations": 10, "population_size": 8},
            "sandbox": {"timeout_sec": 30, "backend": "invalid"},
        }
        ok, errors = validate_config_snapshot(snapshot)
        assert not ok

    def test_create_audit_snapshot_masks(self):
        settings = {
            "models": {"heavy": ["gpt-4o"]},
            "api_key": "sk-secret123",
        }
        snapshot = create_audit_snapshot(settings, evaluator_spec="mod:Cls", config_path="c.toml")
        assert snapshot["evaluator"] == "mod:Cls"
        assert snapshot["config_path"] == "c.toml"
        assert "***" in snapshot["settings"]["api_key"]
        assert snapshot["settings"]["models"]["heavy"] == ["gpt-4o"]


# --------------------------------------------------------------------------- #
#  Domain Plugins
# --------------------------------------------------------------------------- #


class TestPlugins:
    def test_quant_plugin_hints(self):
        plugin = QuantPlugin()
        hints = plugin.get_domain_hints("optimize quant alpha strategy")
        assert len(hints) > 0
        assert any("过拟合" in h or "overfitting" in h.lower() for h in hints)

    def test_quant_plugin_no_hints_for_unrelated(self):
        plugin = QuantPlugin()
        hints = plugin.get_domain_hints("sort an array")
        assert hints == []

    def test_quant_plugin_rag_corpus(self):
        plugin = QuantPlugin()
        corpus = plugin.get_rag_corpus()
        assert corpus is not None
        assert len(corpus) >= 1

    def test_geo_plugin_hints(self):
        plugin = GeoPlugin()
        hints = plugin.get_domain_hints("optimize spatial index for geo data")
        assert len(hints) > 0
        assert any("坐标" in h or "coordinate" in h.lower() for h in hints)

    def test_plugin_registry(self):
        registry = PluginRegistry()
        registry.register(QuantPlugin())
        registry.register(GeoPlugin())
        assert set(registry.list_plugins()) == {"quant", "geo"}
        hints = registry.get_all_domain_hints("quant geo task")
        assert len(hints) > 0


# --------------------------------------------------------------------------- #
#  LLM Novelty Judge
# --------------------------------------------------------------------------- #


class TestLLMNoveltyJudge:
    def test_no_llm_defaults_to_penalty(self):
        judge = LLMNoveltyJudge(llm=None)
        assert judge.judge("some thought", None, 0.9) == "allow_with_penalty"

    def test_with_llm_parses_response(self):
        class StubLLM:
            def __init__(self, content: str):
                self._content = content

            def chat(self, messages, **kw):
                class R:
                    content = self._content

                return R()

        judge = LLMNoveltyJudge(llm=StubLLM("reject"))
        assert judge.judge("thought", None, 0.9) == "reject"

        judge2 = LLMNoveltyJudge(llm=StubLLM("allow"))
        assert judge2.judge("thought", None, 0.9) == "allow"

    def test_novelty_gate_with_llm_judge_in_borderline(self):
        """NoveltyGate 在 borderline 区域应调用 LLM judge."""
        calls = []

        class StubLLM:
            def chat(self, messages, **kw):
                calls.append(messages)

                class R:
                    content = "allow"

                return R()

        judge = LLMNoveltyJudge(llm=StubLLM())
        gate = NoveltyGate(
            embedding_threshold=0.92,
            borderline_low=0.85,
            borderline_high=0.95,
            llm_judge=judge,
        )
        result = gate.check(
            thought="novel idea",
            existing_similarities=[0.89],  # 在 borderline 区域
        )
        assert result.decision in (NoveltyDecision.ALLOW, NoveltyDecision.ALLOW_WITH_PENALTY)
        assert len(calls) == 1  # LLM 被调用


# --------------------------------------------------------------------------- #
#  Audit Report Generator
# --------------------------------------------------------------------------- #


class TestAuditReport:
    def test_generate_report_for_empty_experiment(self, db):
        exp_repo = ExperimentRepository(db)
        exp = exp_repo.create(task_id="audit-test", task_name="audit-test", config_snapshot={})

        generator = AuditReportGenerator(db)
        report = generator.generate(exp.id)
        assert report.experiment.experiment_id == exp.id
        assert report.best_candidate is None
        assert report.candidates == []
        assert report.policies == []

    def test_generate_report_with_candidates(self, db):
        exp_repo = ExperimentRepository(db)
        cr = CandidateRepository(db)
        exp = exp_repo.create(task_id="t", task_name="t", config_snapshot={"k": "v"})

        # 注册版本行（满足 FK 约束）
        db.execute(
            "INSERT INTO task_evaluator_version(id,name,semantic_version,"
            "implementation_hash,task_semantics_hash,score_schema,immutable_core) "
            "VALUES ('ev@1','ev','1.0.0','h','h','{}',1)"
        )
        db.execute(
            "INSERT INTO execution_environment_version(id,backend,resource_policy,network_policy) "
            "VALUES ('env1','docker','{}','none')"
        )
        # 创建 Artifact 记录（满足 FK 约束）
        db.execute(
            "INSERT INTO artifact(hash,artifact_type,byte_size,media_type,relative_path) "
            "VALUES ('abc123','source',100,'text/plain','sha256/ab/abc123')"
        )

        # 创建候选 + 评估
        cand = cr.create_candidate(
            experiment_id=exp.id,
            task_id="t",
            generation=1,
            artifact_hash="abc123",
            search_policy_id="p1",
        )
        db.execute(
            "INSERT INTO evaluation_run(id,experiment_id,candidate_id,"
            "evaluator_version_id,environment_version_id,status,passed,primary_score) "
            "VALUES ('run1',?,?,?,?, 'completed',1,0.85)",
            (exp.id, cand.id, "ev@1", "env1"),
        )

        generator = AuditReportGenerator(db)
        report = generator.generate(exp.id, include_all_candidates=True)

        assert len(report.candidates) >= 1
        entry = report.candidates[0]
        assert entry.candidate_id == cand.id
        assert len(entry.evaluations) == 1
        assert entry.evaluations[0]["primary_score"] == 0.85

    def test_report_to_json_serializable(self, db):
        exp_repo = ExperimentRepository(db)
        exp = exp_repo.create(task_id="t", task_name="t", config_snapshot={})

        generator = AuditReportGenerator(db)
        report = generator.generate(exp.id)
        js = report.to_json()
        data = json.loads(js)
        assert "experiment" in data
        assert "candidates" in data
        assert "policies" in data

    def test_lineage_traversal(self, db):
        """血缘链应从 best 向上遍历所有父代."""
        exp_repo = ExperimentRepository(db)
        cr = CandidateRepository(db)
        exp = exp_repo.create(task_id="t", task_name="t", config_snapshot={})

        db.execute(
            "INSERT INTO task_evaluator_version(id,name,semantic_version,"
            "implementation_hash,task_semantics_hash,score_schema,immutable_core) "
            "VALUES ('ev@1','ev','1.0.0','h','h','{}',1)"
        )
        db.execute(
            "INSERT INTO execution_environment_version(id,backend,resource_policy,network_policy) "
            "VALUES ('env1','docker','{}','none')"
        )
        db.execute(
            "INSERT INTO artifact(hash,artifact_type,byte_size,media_type,relative_path) "
            "VALUES ('parent','source',50,'text/plain','sha256/pa/parent')"
        )
        db.execute(
            "INSERT INTO artifact(hash,artifact_type,byte_size,media_type,relative_path) "
            "VALUES ('child','source',60,'text/plain','sha256/ch/child')"
        )

        parent = cr.create_candidate(
            experiment_id=exp.id,
            task_id="t",
            generation=0,
            artifact_hash="parent",
            search_policy_id="p",
        )
        child = cr.create_candidate(
            experiment_id=exp.id,
            task_id="t",
            generation=1,
            artifact_hash="child",
            search_policy_id="p",
            parents=[(parent.id, "mutate")],
        )
        db.execute(
            "INSERT INTO evaluation_run(id,experiment_id,candidate_id,"
            "evaluator_version_id,environment_version_id,status,passed,primary_score) "
            "VALUES ('run_c',?,?,?,?, 'completed',1,0.9)",
            (exp.id, child.id, "ev@1", "env1"),
        )

        generator = AuditReportGenerator(db)
        report = generator.generate(exp.id)

        # best=child, 血缘链包含 child + parent
        ids = {c.candidate_id for c in report.candidates}
        assert child.id in ids
        assert parent.id in ids


# --------------------------------------------------------------------------- #
#  Policy Export/Import (S9-12)
# --------------------------------------------------------------------------- #


class TestPolicyExportImport:
    def test_export_then_import_roundtrip(self, db):
        archive = PolicyArchive(db)
        genome = SearchPolicyGenome(retrieval_budget=12)
        original = archive.create_policy(genome, experiment_id=None, risk_level="L0")
        archive.promote_to_champion(original.id)

        snapshot = archive.export_policy(original.id)
        assert snapshot["genome"]["retrieval_budget"] == 12

        imported = archive.import_policy(snapshot)
        assert imported.genome.retrieval_budget == 12
        assert imported.id != original.id  # 新 ID

    def test_import_invalid_snapshot_raises(self, db):
        archive = PolicyArchive(db)
        with pytest.raises((KeyError, TypeError)):
            archive.import_policy({"no_genome": True})


# --------------------------------------------------------------------------- #
#  S5-10: Agent retry/backoff/fallback
# --------------------------------------------------------------------------- #


class TestAgentRetryBackoff:
    """S5-10: LLM Gateway retry/backoff/fallback."""

    def test_retry_on_failure_then_succeed(self):
        """失败后重试应最终成功."""
        import sys
        from types import ModuleType

        from omnievolve.agents.llm_gateway import LLMGateway

        call_count = [0]

        class StubResponse:
            def __init__(self, content):
                self._content = content

            class _Choice:
                class _Message:
                    def __init__(self, c):
                        self.content = c

                def __init__(self, c):
                    self.message = self._Message(c)

            def __getattr__(self, name):
                if name == "choices":
                    return [self._Choice(self._content)]
                raise AttributeError(name)

            def model_dump(self):
                return {}

        class StubUsage:
            prompt_tokens = 10
            completion_tokens = 5
            total_tokens = 15

        class FlakyLiteLLM(ModuleType):
            @staticmethod
            def completion(**kwargs):
                call_count[0] += 1
                if call_count[0] < 3:
                    raise RuntimeError("transient error")
                resp = StubResponse('{"thought": "ok"}')
                resp.usage = StubUsage()
                return resp

        fake_module = FlakyLiteLLM("litellm")
        original = sys.modules.get("litellm")
        sys.modules["litellm"] = fake_module  # type: ignore[assignment]

        try:
            gateway = LLMGateway(max_retries=3, retry_backoff_base=0.01)
            response = gateway.chat([{"role": "user", "content": "test"}])
            assert response.content == '{"thought": "ok"}'
            assert call_count[0] == 3
        finally:
            if original:
                sys.modules["litellm"] = original
            else:
                del sys.modules["litellm"]

    def test_fallback_model_on_exhaustion(self):
        """主模型重试耗尽后应切换到 fallback."""
        import sys
        from types import ModuleType

        from omnievolve.agents.llm_gateway import LLMGateway

        primary_calls = [0]
        fallback_calls = [0]

        class StubResponse:
            def __init__(self, content):
                self._content = content

            class _Choice:
                class _Message:
                    def __init__(self, c):
                        self.content = c

                def __init__(self, c):
                    self.message = self._Message(c)

            def __getattr__(self, name):
                if name == "choices":
                    return [self._Choice(self._content)]
                raise AttributeError(name)

            def model_dump(self):
                return {}

        class StubUsage:
            prompt_tokens = 10
            completion_tokens = 5
            total_tokens = 15

        class StubLiteLLM(ModuleType):
            @staticmethod
            def completion(**kwargs):
                model = kwargs.get("model", "")
                if "primary" in model:
                    primary_calls[0] += 1
                    raise RuntimeError("primary always fails")
                fallback_calls[0] += 1
                resp = StubResponse('{"ok": true}')
                resp.usage = StubUsage()
                return resp

        fake_module = StubLiteLLM("litellm")
        original = sys.modules.get("litellm")
        sys.modules["litellm"] = fake_module  # type: ignore[assignment]

        try:
            gateway = LLMGateway(
                default_model="primary-model",
                fallback_model="fallback-model",
                max_retries=2,
                retry_backoff_base=0.01,
            )
            response = gateway.chat([{"role": "user", "content": "test"}])
            assert "ok" in response.content
            assert response.model == "fallback-model"
            assert fallback_calls[0] == 1
        finally:
            if original:
                sys.modules["litellm"] = original
            else:
                del sys.modules["litellm"]


# --------------------------------------------------------------------------- #
#  S5-09: Structured output repair
# --------------------------------------------------------------------------- #


class TestStructuredOutputRepair:
    """S5-09: 结构化输出校验与有限修复."""

    def test_valid_json_parsed(self):
        from omnievolve.agents.coder import Coder
        from omnievolve.agents.llm_gateway import FakeLLM

        coder = Coder(FakeLLM(['{"full_code": "x = 1", "diff": "add"}']))
        from omnievolve.agents.base import AgentContext, ThoughtOutput

        ctx = AgentContext(experiment_id="e", task_id="t", generation=1)
        thought = ThoughtOutput(thought="test", rationale="r")
        code = coder.generate_code(ctx, thought)
        assert code.full_code == "x = 1"

    def test_code_block_extraction_repair(self):
        """JSON 失败时提取 ```python 代码块."""
        from omnievolve.agents.coder import Coder
        from omnievolve.agents.llm_gateway import FakeLLM

        coder = Coder(FakeLLM(["Here is the code:\n```python\ndef solve():\n    return 42\n```\n"]))
        from omnievolve.agents.base import AgentContext, ThoughtOutput

        ctx = AgentContext(experiment_id="e", task_id="t", generation=1)
        thought = ThoughtOutput(thought="t", rationale="r")
        code = coder.generate_code(ctx, thought)
        assert "def solve" in code.full_code
        assert "return 42" in code.full_code

    def test_raw_fallback(self):
        """无 JSON 无代码块时回退为裸代码."""
        from omnievolve.agents.coder import Coder
        from omnievolve.agents.llm_gateway import FakeLLM

        coder = Coder(FakeLLM(["x = 42\nprint(x)"]))
        from omnievolve.agents.base import AgentContext, ThoughtOutput

        ctx = AgentContext(experiment_id="e", task_id="t", generation=1)
        thought = ThoughtOutput(thought="t", rationale="r")
        code = coder.generate_code(ctx, thought)
        assert "x = 42" in code.full_code
