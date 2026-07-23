"""AsyncPipelineEngine 测试 — Step 11: 48% → 75%+."""

from __future__ import annotations

from unittest.mock import MagicMock

from omnievolve.engine.async_engine import AsyncPipelineEngine


class TestAsyncPipelineEngine:
    """AsyncPipelineEngine 单元测试."""

    def _make_engine(self):
        engine = MagicMock()
        engine._config = MagicMock()
        engine._config.population_size = 4
        engine._config.max_generations = 2
        engine._config.island_count = 1
        engine._config.health_window_gens = 3
        engine._config.self_evolve_enabled = False
        engine._budget_guard = MagicMock()
        engine._budget_guard.state.is_exhausted = False
        engine._best_candidate = None
        engine._current_generation = 0
        return engine

    def test_init(self):
        engine = self._make_engine()
        pipeline = AsyncPipelineEngine(engine)
        assert pipeline is not None
        assert pipeline._max_proposal_slots == 4
        assert pipeline._ewma_alpha == 0.3

    def test_update_ewma_cold_start(self):
        engine = self._make_engine()
        pipeline = AsyncPipelineEngine(engine)
        assert pipeline._sampling_ewma is None
        pipeline._update_ewma("sampling", 2.0)
        assert pipeline._sampling_ewma == 2.0

    def test_update_ewma_subsequent(self):
        engine = self._make_engine()
        pipeline = AsyncPipelineEngine(engine)
        pipeline._sampling_ewma = 2.0
        pipeline._update_ewma("sampling", 4.0)
        assert abs(pipeline._sampling_ewma - 2.6) < 0.01

    def test_update_ewma_commit(self):
        engine = self._make_engine()
        pipeline = AsyncPipelineEngine(engine)
        pipeline._update_ewma("commit", 3.0)
        assert pipeline._eval_ewma == 3.0

    def test_compute_pipeline_target_cold_start(self):
        engine = self._make_engine()
        pipeline = AsyncPipelineEngine(engine)
        target = pipeline._compute_pipeline_target()
        assert target == engine._config.population_size

    def test_compute_pipeline_target_warm(self):
        engine = self._make_engine()
        pipeline = AsyncPipelineEngine(engine)
        pipeline._sampling_ewma = 2.0
        pipeline._eval_ewma = 1.0
        target = pipeline._compute_pipeline_target()
        assert target >= engine._config.population_size

    def test_compute_pipeline_target_cap(self):
        engine = self._make_engine()
        pipeline = AsyncPipelineEngine(engine)
        pipeline._sampling_ewma = 100.0
        pipeline._eval_ewma = 1.0
        target = pipeline._compute_pipeline_target()
        assert target <= engine._config.population_size * 5
