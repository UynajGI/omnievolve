"""小模块补刀测试 — router, selection, novelty, telemetry, llm_gateway."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
#  router.py
# --------------------------------------------------------------------------- #


class TestModelSlot:
    def test_create_slot(self):
        from omnievolve.agents.router import ModelSlot

        slot = ModelSlot(
            name="gpt-4o",
            tier="heavy",
            cost_per_1k_input=0.01,
            cost_per_1k_output=0.03,
            avg_latency_ms=2000.0,
            capabilities={"reasoning"},
        )
        assert slot.name == "gpt-4o"
        assert slot.tier == "heavy"


class TestModelRouter:
    def test_router_init_no_slots(self):
        from omnievolve.agents.router import ModelRouter

        router = ModelRouter([])
        assert router is not None

    def test_get_stats(self):
        from omnievolve.agents.router import ModelRouter, ModelSlot

        slots = [ModelSlot("m1", "light", 0.001, 0.003, 500.0, {"code"})]
        router = ModelRouter(slots)
        stats = router.get_stats()
        assert "algorithm" in stats


# --------------------------------------------------------------------------- #
#  selection.py
# --------------------------------------------------------------------------- #


class TestParentSelector:
    def test_init(self, db):
        from omnievolve.engine.selection import ParentSelector

        selector = ParentSelector(db, strategy="tournament")
        assert selector is not None

    def test_select_empty_returns_empty(self, db):
        from omnievolve.engine.selection import ParentSelector

        selector = ParentSelector(db)
        result = selector.select("no-exp", "ev", "env", count=3)
        assert result == []


# --------------------------------------------------------------------------- #
#  novelty.py (additional)
# --------------------------------------------------------------------------- #


class TestNoveltyGateExtended:
    def test_custom_thresholds(self):
        from omnievolve.engine.novelty import NoveltyGate

        gate = NoveltyGate(
            embedding_threshold=0.85,
            borderline_low=0.75,
            borderline_high=0.95,
        )
        # 中间值，不触发 high reject
        result = gate.check("test", existing_similarities=[0.90])
        assert result.decision.value in ("allow", "allow_with_penalty")

    def test_llm_judge_none_ok(self):
        from omnievolve.engine.novelty import NoveltyGate

        gate = NoveltyGate(llm_judge=None)
        result = gate.check("thought", code="x=1", existing_similarities=[0.90])
        assert result is not None


# --------------------------------------------------------------------------- #
#  telemetry.py
# --------------------------------------------------------------------------- #


class TestTelemetryAggregator:
    def test_aggregator_init(self, db):
        from omnievolve.eval.telemetry import TelemetryAggregator

        agg = TelemetryAggregator(db)
        assert agg is not None

    def test_aggregate_empty(self, db):
        from omnievolve.eval.telemetry import TelemetryAggregator

        agg = TelemetryAggregator(db)
        metrics = agg.aggregate("no-exp", 0, 1)
        assert metrics is not None


class TestHealthPolicy:
    def test_init_defaults(self):
        from omnievolve.eval.telemetry import HealthPolicy

        hp = HealthPolicy()
        assert hp is not None

    def test_init_custom_thresholds(self):
        from omnievolve.eval.telemetry import HealthPolicy

        hp = HealthPolicy(
            roi_warn_threshold=0.01,
            entropy_warn_threshold=0.5,
            stagnation_trigger=5,
        )
        assert hp is not None


class TestDashboardDataExporter:
    def test_get_snapshot_empty(self, db):
        from omnievolve.eval.telemetry import (
            DashboardDataExporter,
            HealthPolicy,
            TelemetryAggregator,
        )

        agg = TelemetryAggregator(db)
        hp = HealthPolicy()
        exporter = DashboardDataExporter(agg, hp)
        snap = exporter.get_snapshot("no-exp", 0, 1)
        assert isinstance(snap, dict)

    def test_get_timeseries_empty(self, db):
        from omnievolve.eval.telemetry import (
            DashboardDataExporter,
            HealthPolicy,
            TelemetryAggregator,
        )

        agg = TelemetryAggregator(db)
        hp = HealthPolicy()
        exporter = DashboardDataExporter(agg, hp)
        ts = exporter.get_timeseries("no-exp")
        assert isinstance(ts, list)

    def test_export_prometheus_empty(self, db):
        from omnievolve.eval.telemetry import (
            DashboardDataExporter,
            HealthPolicy,
            TelemetryAggregator,
        )

        agg = TelemetryAggregator(db)
        hp = HealthPolicy()
        exporter = DashboardDataExporter(agg, hp)
        result = exporter.export_prometheus("no-exp")
        assert isinstance(result, str)


# --------------------------------------------------------------------------- #
#  llm_gateway.py
# --------------------------------------------------------------------------- #


class TestLLMResponse:
    def test_create_response(self):
        from omnievolve.agents.llm_gateway import LLMResponse

        r = LLMResponse(
            content="hello",
            model="gpt-4o",
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
            latency_ms=500.0,
        )
        assert r.content == "hello"
        assert r.total_tokens == 30


class TestLLMCallRecord:
    def test_create_record(self):
        from omnievolve.agents.llm_gateway import LLMCallRecord

        r = LLMCallRecord(
            id="r1",
            experiment_id="e1",
            agent_role="director",
            model="gpt-4o",
            prompt_version_id="pv1",
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
            cost_usd=0.001,
            latency_ms=500.0,
            request_hash="abc",
            response_hash="def",
            created_at="2026-01-01T00:00:00Z",
        )
        assert r.agent_role == "director"
        assert r.cost_usd == 0.001


class TestLLMGateway:
    def test_init(self, db):
        from omnievolve.agents.llm_gateway import LLMGateway

        gw = LLMGateway(db, default_model="gpt-4o-mini")
        assert gw is not None

    def test_get_stats_initial(self, db):
        from omnievolve.agents.llm_gateway import LLMGateway

        gw = LLMGateway(db)
        stats = gw.get_stats()
        assert stats["calls"] == 0


# --------------------------------------------------------------------------- #
#  Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def db():
    from omnievolve.storage.db import create_memory_database
    from omnievolve.storage.migrations import initialize_database

    database = create_memory_database()
    initialize_database(database)
    yield database
    database.close()
