"""ParentSelector 测试 — 全策略覆盖，重点 power_law / weighted."""

from __future__ import annotations

import pytest

from omnievolve.engine.selection import ExplorationSelector, ParentSelector


def _seed_candidates(db, experiment_id, evaluator_version, env_version, n=10):
    """向 DB 插入 n 个带分数的候选."""
    from omnievolve.storage.repositories.candidate_repo import CandidateRepository

    # 创建外键依赖行
    db.execute(
        "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
        (experiment_id, "task_test", "test", "{}"),
    )
    db.execute(
        """INSERT INTO task_evaluator_version
           (id, name, semantic_version, implementation_hash, task_semantics_hash, score_schema)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (evaluator_version, "test", "1.0", "hash", "sem", "{}"),
    )
    db.execute(
        """INSERT INTO execution_environment_version (id, backend, resource_policy, network_policy)
           VALUES (?, ?, ?, ?)""",
        (env_version, "subprocess", "{}", "none"),
    )

    repo = CandidateRepository(db)
    cids = []
    for i in range(n):
        artifact_hash = f"a{i:060d}"
        db.execute(
            "INSERT INTO artifact (hash, artifact_type, byte_size, relative_path) VALUES (?, ?, ?, ?)",
            (artifact_hash, "source", 100, f"sha256/{artifact_hash[:2]}/{artifact_hash}"),
        )
        candidate = repo.create_candidate(
            experiment_id=experiment_id,
            task_id="task_test",
            generation=0,
            artifact_hash=artifact_hash,
            search_policy_id="default",
            island_id="default",
        )
        cids.append(candidate.id)
        db.execute(
            """INSERT INTO evaluation_run
               (id, experiment_id, candidate_id, evaluator_version_id, environment_version_id,
                status, passed, primary_score, attempt, split_name)
               VALUES (?, ?, ?, ?, ?, 'completed', 1, ?, 1, 'all')""",
            (
                f"er_{experiment_id}_{i}",
                experiment_id,
                candidate.id,
                evaluator_version,
                env_version,
                float(i),
            ),
        )
    return cids


@pytest.fixture
def seeded_db(db):
    """DB with 10 candidates, scores 0.0..9.0."""
    cids = _seed_candidates(db, "exp_test", "ev_v1", "env_v1", n=10)
    return db, cids


class TestSelectBest:
    def test_returns_highest_score(self, seeded_db):
        db, cids = seeded_db
        selector = ParentSelector(db, strategy="best")
        result = selector.select("exp_test", "ev_v1", "env_v1", count=3)
        assert len(result) == 3
        # Top 3 scores are 9, 8, 7
        for cid in result:
            idx = cids.index(cid)
            assert idx >= 7


class TestSelectTournament:
    def test_returns_correct_count(self, seeded_db):
        db, _ = seeded_db
        selector = ParentSelector(db, strategy="tournament", tournament_size=3)
        result = selector.select("exp_test", "ev_v1", "env_v1", count=5)
        assert len(result) == 5

    def test_tournament_size_clamped(self, seeded_db):
        """Tournament size > candidate count should not crash."""
        db, _ = seeded_db
        selector = ParentSelector(db, strategy="tournament", tournament_size=100)
        result = selector.select("exp_test", "ev_v1", "env_v1", count=1)
        assert len(result) == 1


class TestSelectRandom:
    def test_returns_correct_count(self, seeded_db):
        db, _ = seeded_db
        selector = ParentSelector(db, strategy="random")
        result = selector.select("exp_test", "ev_v1", "env_v1", count=4)
        assert len(result) == 4


class TestSelectPowerLaw:
    def test_returns_correct_count(self, seeded_db):
        db, _ = seeded_db
        selector = ParentSelector(db, strategy="power_law", power_law_alpha=1.0)
        result = selector.select("exp_test", "ev_v1", "env_v1", count=3)
        assert len(result) == 3

    def test_alpha_zero_approximates_uniform(self, seeded_db):
        """α=0 → uniform sampling — all candidates should be reachable."""
        db, cids = seeded_db
        selector = ParentSelector(db, strategy="power_law", power_law_alpha=0.0)
        selected_set = set()
        for _ in range(200):
            result = selector.select("exp_test", "ev_v1", "env_v1", count=1)
            selected_set.update(result)
        # With uniform sampling over 200 draws, should hit most of 10 candidates
        assert len(selected_set) >= 7

    def test_high_alpha_concentrates_on_top(self, seeded_db):
        """α→∞ → hill-climbing, top-ranked candidates selected most."""
        db, cids = seeded_db
        selector = ParentSelector(db, strategy="power_law", power_law_alpha=5.0)
        selected = []
        for _ in range(100):
            result = selector.select("exp_test", "ev_v1", "env_v1", count=1)
            selected.extend(result)
        # Score 9.0 is rank 1 → should dominate
        top_cid = cids[9]
        assert selected.count(top_cid) > selected.count(cids[0])

    def test_without_replacement(self, seeded_db):
        """count > 1 should not return duplicates."""
        db, _ = seeded_db
        selector = ParentSelector(db, strategy="power_law")
        result = selector.select("exp_test", "ev_v1", "env_v1", count=5)
        assert len(result) == len(set(result))


class TestSelectWeighted:
    def test_returns_correct_count(self, seeded_db):
        db, _ = seeded_db
        selector = ParentSelector(db, strategy="weighted", weighted_lambda=10.0)
        result = selector.select("exp_test", "ev_v1", "env_v1", count=3)
        assert len(result) == 3

    def test_without_replacement(self, seeded_db):
        db, _ = seeded_db
        selector = ParentSelector(db, strategy="weighted")
        result = selector.select("exp_test", "ev_v1", "env_v1", count=5)
        assert len(result) == len(set(result))

    def test_balances_score_and_offspring(self, db):
        """High offspring count should reduce selection probability."""
        cids = _seed_candidates(db, "exp_w", "ev_w", "env_w", n=5)
        # Give top scorer many offspring (update existing search_state row)
        db.execute(
            "UPDATE candidate_search_state SET offspring_count = 100 WHERE candidate_id = ?",
            (cids[4],),  # score=4.0, the highest
        )
        selector = ParentSelector(db, strategy="weighted", weighted_lambda=5.0)
        selected = []
        for _ in range(100):
            result = selector.select("exp_w", "ev_w", "env_w", count=1)
            selected.extend(result)
        # The saturated candidate (score 4, offspring 100) should appear less
        # than a fresh high-scorer would
        assert len(selected) == 100


class TestExcludeIds:
    def test_excluded_candidates_not_returned(self, seeded_db):
        db, cids = seeded_db
        selector = ParentSelector(db, strategy="best")
        exclude = cids[7:]  # exclude top 3
        result = selector.select("exp_test", "ev_v1", "env_v1", count=3, exclude_ids=exclude)
        for cid in result:
            assert cid not in exclude


class TestEmptyDb:
    def test_no_candidates_returns_empty(self, db):
        selector = ParentSelector(db, strategy="best")
        result = selector.select("no_exp", "ev", "env", count=5)
        assert result == []


class TestExplorationSelector:
    def test_prefers_low_visit_count(self, db):
        cids = _seed_candidates(db, "exp_expl", "ev_e", "env_e", n=5)
        # candidate 0 has 0 visits (default), others have 10
        for i in range(1, 5):
            db.execute(
                "UPDATE candidate_search_state SET visit_count = 10 WHERE candidate_id = ?",
                (cids[i],),
            )
        selector = ExplorationSelector(db)
        result = selector.select("exp_expl", "ev_e", "env_e", count=1)
        assert result == [cids[0]]


class TestStrategyRouting:
    def test_unknown_strategy_defaults_to_random(self, seeded_db):
        db, _ = seeded_db
        selector = ParentSelector(db, strategy="nonexistent")
        result = selector.select("exp_test", "ev_v1", "env_v1", count=2)
        assert len(result) == 2
