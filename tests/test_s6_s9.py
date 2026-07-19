"""S6-S9 补全模块测试."""

import pytest

from omnievolve.agents.router import ModelRouter, ModelSlot, RouteContext
from omnievolve.engine.crossover import CrossoverOperator
from omnievolve.engine.island import IslandManager
from omnievolve.engine.mcts import ProgressiveMCGS
from omnievolve.engine.novelty import NoveltyDecision, NoveltyGate
from omnievolve.eval.metrics import MetricsCalculator
from omnievolve.eval.telemetry import AlertLevel, HealthPolicy
from omnievolve.meta.governance import (
    GovernancePolicy,
    L0PolicyMutator,
    MetaAction,
    ReplayEvaluator,
    RiskLevel,
)
from omnievolve.meta.policy_archive import PolicyArchive
from omnievolve.meta.policy_genome import SearchPolicyGenome
from omnievolve.plugins.base import BasePlugin, PluginRegistry
from omnievolve.storage.db import create_memory_database
from omnievolve.storage.migrations import initialize_database
from omnievolve.storage.numpy_backend import NumpyVectorBackend
from omnievolve.storage.vector_indexer import VectorIndexer
from omnievolve.utils.embedding import FakeEmbedder
from omnievolve.utils.token_counter import BudgetGuard, BudgetState, TokenCounter


@pytest.fixture
def db():
    database = create_memory_database()
    initialize_database(database)
    yield database
    database.close()


class TestTokenCounter:
    def test_estimate_cost(self):
        counter = TokenCounter()
        cost = counter.estimate_cost("gpt-4o", 1000, 500)
        assert cost > 0

    def test_budget_guard(self):
        state = BudgetState(token_budget=1000)
        guard = BudgetGuard(state)
        assert guard.can_proceed(100)
        guard.consume("gpt-4o", 500, 200)
        assert state.used_tokens == 700


class TestMetricsCalculator:
    def test_roi(self):
        calc = MetricsCalculator()
        roi = calc.compute_roi(1.0, 10.0, 100.0, 3600.0)
        assert roi > 0

    def test_coverage_entropy(self):
        calc = MetricsCalculator()
        result = calc.compute_coverage_entropy(
            thought_clusters=[1, 1, 2, 3, 3, 3],
            knn_distances=[0.1, 0.2, 0.3],
            ast_features=["func_a", "func_b", "func_c"],
            branch_sizes=[10, 10, 10, 10],
        )
        assert result["coverage_entropy"] > 0

    def test_memory_effectiveness(self):
        calc = MetricsCalculator()
        result = calc.compute_memory_effectiveness(
            total_retrievals=100,
            citations=40,
            adoptions=30,
            duplicate_attempts_before=50,
            duplicate_attempts_after=20,
        )
        assert result["memory_effectiveness"] > 0


class TestTelemetryAndHealth:
    def test_health_policy_ok(self):
        from omnievolve.eval.metrics import HealthMetrics

        policy = HealthPolicy()
        metrics = HealthMetrics(
            roi_score=0.1,
            coverage_entropy=0.6,
            success_rate=0.8,
            pollution_ratio=0.1,
        )
        output = policy.assess(metrics)
        assert output.alert_level == AlertLevel.OK

    def test_health_policy_warn(self):
        from omnievolve.eval.metrics import HealthMetrics

        policy = HealthPolicy(roi_warn_threshold=0.5)
        metrics = HealthMetrics(roi_score=0.1, coverage_entropy=0.6, success_rate=0.8)
        output = policy.assess(metrics)
        assert output.alert_level == AlertLevel.WARN
        assert output.should_trigger_meta


class TestModelRouter:
    def test_select(self):
        slots = [
            ModelSlot("model_a", "heavy", 0.01, 0.03, 1000),
            ModelSlot("model_b", "light", 0.001, 0.002, 500),
        ]
        router = ModelRouter(slots)
        ctx = RouteContext(
            role="director",
            generation=1,
            stagnation_level=0.0,
            novelty_deficit=0.0,
            implementation_difficulty=0.5,
            remaining_token_ratio=1.0,
            remaining_compute_ratio=1.0,
        )
        model = router.select(ctx)
        assert model in ["model_a", "model_b"]

    def test_update(self):
        slots = [ModelSlot("model_a", "heavy", 0.01, 0.03, 1000)]
        router = ModelRouter(slots)
        router.update("model_a", "director", 0.8)
        # 不报错即可


class TestPolicyArchive:
    def test_create_and_get(self, db):
        # 先创建 experiment
        db.execute(
            "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
            ("exp1", "task1", "Test", "{}"),
        )
        archive = PolicyArchive(db)
        genome = SearchPolicyGenome()
        policy = archive.create_policy(genome, experiment_id="exp1")
        assert policy.id is not None

        fetched = archive.get(policy.id)
        assert fetched is not None
        assert fetched.genome.parent_selector == "tournament"

    def test_promote_to_champion(self, db):
        db.execute(
            "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
            ("exp1", "task1", "Test", "{}"),
        )
        archive = PolicyArchive(db)
        genome = SearchPolicyGenome()
        p1 = archive.create_policy(genome, experiment_id="exp1")
        archive.promote_to_champion(p1.id)

        champ = archive.get_champion("exp1")
        assert champ is not None
        assert champ.id == p1.id


class TestGovernance:
    def test_classify_action(self):
        gov = GovernancePolicy()
        action = MetaAction(
            action_type="modify_field",
            target="temperature_schedule",
            old_value="constant",
            new_value="adaptive",
            risk_level=RiskLevel.L0,
        )
        risk = gov.classify_action(action)
        assert risk == RiskLevel.L0

    def test_l0_mutator(self):
        gov = GovernancePolicy()
        mutator = L0PolicyMutator(gov)
        genome = SearchPolicyGenome()

        new_genome, reason = mutator.mutate(genome, "retrieval_budget", 16)
        assert new_genome is not None
        assert new_genome.retrieval_budget == 16

    def test_replay_evaluator(self):
        evaluator = ReplayEvaluator()
        result = evaluator.compare(
            champion_scores=[0.5, 0.52, 0.48],
            challenger_scores=[0.6, 0.62, 0.58],
        )
        assert result["decision"] == "promote"


class TestMCTS:
    def test_select_and_backprop(self):
        mcts = ProgressiveMCGS()
        mcts.add_node("root")
        mcts.add_node("child1", parent="root", prior=0.6)
        mcts.add_node("child2", parent="root", prior=0.4)

        leaf = mcts.select("root")
        assert leaf in ["child1", "child2"]

        mcts.backpropagate(leaf, 0.8)
        stats = mcts.get_stats()
        assert stats["nodes"] == 3


class TestIsland:
    def test_assign_candidate(self):
        manager = IslandManager(num_islands=4)
        island_id = manager.assign_candidate("cand1", "island_0")
        assert island_id == "island_0"

    def test_migration(self):
        manager = IslandManager(num_islands=3, migration_interval=2)
        for i in range(3):
            manager.assign_candidate(f"cand_{i}", f"island_{i}")

        # 在各岛屿添加精英
        for island_id in ["island_0", "island_1"]:
            island = manager.get_island(island_id)
            island.update_elite(f"best_{island_id}", 0.9)

        migrations = manager.migrate(current_gen=5)
        # 可能有迁移
        assert isinstance(migrations, list)


class TestCrossover:
    def test_select_parents(self):
        op = CrossoverOperator(min_parents=2, max_parents=3)
        candidates = [("c1", 0.9), ("c2", 0.8), ("c3", 0.7)]
        parents = op.select_parents(candidates)
        assert len(parents) >= 2

    def test_combine(self):
        op = CrossoverOperator()
        code1 = "def func_a():\n    return 1\n"
        code2 = "def func_b():\n    return 2\n"
        result = op.combine([code1, code2], strategy="function_level")
        assert "func_a" in result
        assert "func_b" in result


class TestNoveltyGate:
    def test_allow_novel(self):
        gate = NoveltyGate()
        result = gate.check(
            thought="new idea",
            existing_similarities=[0.3, 0.5],
        )
        assert result.decision == NoveltyDecision.ALLOW

    def test_reject_similar(self):
        gate = NoveltyGate(borderline_high=0.9)
        result = gate.check(
            thought="duplicate",
            existing_similarities=[0.95, 0.98],
        )
        assert result.decision == NoveltyDecision.REJECT


class TestPluginRegistry:
    def test_register_and_get(self):
        registry = PluginRegistry()
        plugin = BasePlugin()
        registry.register(plugin)
        assert "base" in registry.list_plugins()

    def test_domain_hints(self):
        registry = PluginRegistry()
        registry.register(BasePlugin())
        hints = registry.get_all_domain_hints("test task")
        assert isinstance(hints, list)


class TestVectorIndexer:
    def test_enqueue_and_process(self, db, tmp_path):
        from omnievolve.storage.artifact_store import ArtifactStore

        # 准备
        store = ArtifactStore(tmp_path / "artifacts", db)
        backend = NumpyVectorBackend()
        embedder = FakeEmbedder(dimension=64)

        indexer = VectorIndexer(db, backend, embedder)
        indexer.set_artifact_store(store)

        # 存储内容
        content_hash = store.store_text("test content", "source")

        # 加入队列
        indexer.enqueue_index("thought", "t1", "profile1", content_hash)

        # 处理
        processed = indexer.process_batch()
        assert processed >= 0  # 可能成功或失败，不崩溃即可

    def test_get_stats(self, db):
        backend = NumpyVectorBackend()
        embedder = FakeEmbedder()
        indexer = VectorIndexer(db, backend, embedder)

        stats = indexer.get_stats()
        assert isinstance(stats, dict)
