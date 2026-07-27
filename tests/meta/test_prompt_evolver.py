"""PromptEvolver 测试 — Step 6: 19% → 90%+."""

from __future__ import annotations

import random

from omnievolve.meta.prompt_evolver import PromptEvolver


class TestPromptEvolver:
    """Prompt 变异器测试."""

    def test_evolve_no_mutation(self):
        """mutation_rate=0 → 返回原 prompt."""
        evolver = PromptEvolver(mutation_rate=0.0)
        random.seed(42)
        prompt = "You are a coder."
        new_prompt, mutations = evolver.evolve(prompt)
        assert new_prompt == prompt
        assert mutations == []

    def test_evolve_with_mutation(self):
        """mutation_rate=1.0 → 返回变异后 prompt + 非空 mutations."""
        evolver = PromptEvolver(mutation_rate=1.0, max_mutations=2)
        random.seed(42)
        prompt = "You are a coder."
        new_prompt, mutations = evolver.evolve(prompt)
        assert len(mutations) >= 1
        assert new_prompt != prompt

    def test_evolve_with_feedback(self):
        """feedback 参数不影响变异选择但传递给 _apply_mutation."""
        evolver = PromptEvolver(mutation_rate=1.0)
        random.seed(42)
        new_prompt, mutations = evolver.evolve("test", feedback="improve speed")
        assert len(mutations) >= 1

    def test_weighted_select_uniform(self):
        """无 performance_data → 均匀采样."""
        evolver = PromptEvolver()
        random.seed(42)
        selected = evolver._weighted_select(3, None)
        assert len(selected) == 3
        assert all(m in PromptEvolver.MUTATIONS for m in selected)

    def test_weighted_select_weighted(self):
        """有 performance_data → 高成功率 mutation 更频繁."""
        evolver = PromptEvolver()
        random.seed(42)
        # add_constraint 成功率 0.9，其他 0.1
        perf = {m: 0.1 for m in PromptEvolver.MUTATIONS}
        perf["add_constraint"] = 0.9
        counts = {m: 0 for m in PromptEvolver.MUTATIONS}
        for _ in range(100):
            selected = evolver._weighted_select(1, perf)
            counts[selected[0]] += 1
        # add_constraint 应被选中更多次
        assert counts["add_constraint"] > 20

    def test_weighted_select_count_exceeds_available(self):
        """count > len(MUTATIONS) → 返回所有."""
        evolver = PromptEvolver()
        random.seed(42)
        selected = evolver._weighted_select(10, None)
        assert len(selected) == len(PromptEvolver.MUTATIONS)

    def test_apply_mutation_add_constraint(self):
        evolver = PromptEvolver()
        random.seed(42)
        result = evolver._apply_mutation("base", "add_constraint", None)
        assert "constraint" in result.lower()

    def test_apply_mutation_add_example(self):
        evolver = PromptEvolver()
        result = evolver._apply_mutation("base", "add_example", None)
        assert "Example" in result

    def test_apply_mutation_rephrase(self):
        evolver = PromptEvolver()
        result = evolver._apply_mutation("base", "rephrase", None)
        assert "Important" in result

    def test_apply_mutation_add_step(self):
        evolver = PromptEvolver()
        random.seed(42)
        result = evolver._apply_mutation("base", "add_step", None)
        assert "Step" in result or "Process" in result

    def test_apply_mutation_remove_redundancy(self):
        evolver = PromptEvolver()
        prompt = "line1\n\n\n\nline2"
        result = evolver._apply_mutation(prompt, "remove_redundancy", None)
        assert "\n\n\n" not in result

    def test_apply_mutation_change_tone(self):
        evolver = PromptEvolver()
        result = evolver._apply_mutation(
            "You are a helper. Your role is to assist.", "change_tone", None
        )
        assert "Act as" in result
        assert "Your mission" in result

    def test_apply_mutation_unknown(self):
        """未知 mutation → 返回原 prompt."""
        evolver = PromptEvolver()
        result = evolver._apply_mutation("base", "nonexistent", None)
        assert result == "base"
