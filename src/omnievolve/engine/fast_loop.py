"""Fast Loop Step — 提取自 EvolutionEngine.

T1 重构第三步：将 _evolve_one + _evaluate_candidate 提取为独立组件。
使用 "method object" 模式：引擎作为数据持有者，控制流移到此类。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from omnievolve.agents.base import AgentContext
from omnievolve.engine.novelty import NoveltyDecision
from omnievolve.eval.task_evaluator import (
    CandidateArtifact,
    EvalOutput,
    EvaluationContext,
)
from omnievolve.exceptions import EvaluatorError, SandboxError, StorageError
from omnievolve.sandbox.base import SandboxPolicy

if TYPE_CHECKING:
    from omnievolve.engine.evolution_engine import EvolutionEngine

logger = logging.getLogger(__name__)


class FastLoopStep:
    """单个候选的完整进化链（步骤 1-11）.

    纯控制流组件 — 所有数据通过 engine 引用访问。
    """

    def __init__(self, engine: EvolutionEngine) -> None:
        self._e = engine

    def evolve_one(
        self,
        generation: int,
        task_name: str,
        island_id: str,
    ) -> tuple[str | None, str]:
        """执行单个候选的完整进化链（步骤 1-11）."""
        e = self._e

        # 步骤 2: 选择父代
        parent_ids, relation = e._select_parents(island_id)  # noqa: SLF001

        # 加载父代代码 / 思想
        parent_codes, parent_thoughts = e._load_parents(parent_ids)  # noqa: SLF001

        # 步骤 1: Router 选择模型
        model = e._select_model(generation)  # noqa: SLF001

        # 步骤 3/可选 crossover
        base_code: str | None = None
        if relation == "crossover" and len(parent_codes) >= 2:
            base_code = e._crossover.combine(parent_codes, strategy="segment")  # noqa: SLF001

        # 检索记忆
        memory_hits = e._memory_store.retrieve(  # noqa: SLF001
            experiment_id=e._experiment_id,  # noqa: SLF001
            task_id=task_name,
            success_only=True,
            limit=e._search_policy.retrieval_budget,  # noqa: SLF001
        )
        memory_summaries = [
            {
                "outcome_summary": str(m.outcome_summary)[:200],
                "scope_level": m.scope_level,
                "success": m.success_flag,
            }
            for m in memory_hits
        ]

        # inspiration programs
        inspiration = e._collect_inspiration_programs(parent_ids)  # noqa: SLF001

        # AM-01: 注入父代码到 inspiration
        for i, pid in enumerate(parent_ids):
            if i < len(parent_codes):
                inspiration.insert(
                    0,
                    {
                        "is_parent": True,
                        "candidate_id": pid,
                        "score": 0.0,
                        "code": parent_codes[i],
                        "source": "parent",
                    },
                )

        ctx = AgentContext(
            experiment_id=e._experiment_id,  # noqa: SLF001
            task_id=task_name,
            generation=generation,
            island_id=island_id,
            parent_candidate_ids=parent_ids,
            parent_thoughts=parent_thoughts,
            parent_artifact_hashes=[],
            inspiration_programs=inspiration,
            memory_hits=memory_summaries,
            meta_scratchpad=e._meta_scratchpad,  # noqa: SLF001
            search_policy_id=e._champion_policy_id,  # noqa: SLF001
            evaluator_version_id=e._evaluator_version_id,  # noqa: SLF001
            environment_version_id=e._environment_version_id,  # noqa: SLF001
            model=model,
            prompt_version_id=e._load_champion_prompt("director"),  # noqa: SLF001
        )

        # 步骤 4: Director
        thought = e._director.evolve_thought(ctx)  # noqa: SLF001

        # 步骤 5: NoveltyGate
        novelty_result = e._novelty_gate.check(thought=thought.thought, code=base_code)  # noqa: SLF001
        if novelty_result.decision == NoveltyDecision.REJECT:
            logger.debug("Thought rejected by novelty gate")
            return None, ""

        # 步骤 6: Coder + Critic retry
        code = e._coder.generate_code(ctx, thought)  # noqa: SLF001
        if not code.full_code.strip():
            if base_code:
                code = type(code)(diff="", full_code=base_code, explanation="crossover baseline")
            elif parent_codes:
                code = type(code)(
                    diff="",
                    full_code=parent_codes[0],
                    explanation="fallback to parent code (diff could not be applied)",
                )

        passed, _ = e._critic.review(code, thought)  # noqa: SLF001
        retries = 0
        while not passed and retries < e._config.novelty_retry_limit:  # noqa: SLF001
            retries += 1
            code = e._coder.generate_code(ctx, thought)  # noqa: SLF001
            passed, _ = e._critic.review(code, thought)  # noqa: SLF001

        if not passed:
            logger.debug("Code rejected by critic after retries")
            return None, ""

        # 步骤 7: 存储 Artifact
        artifact_hash = e._artifact_store.store_text(code.full_code, "source")  # noqa: SLF001

        # 步骤 8: 创建候选
        parents_with_relation = [(pid, relation) for pid in parent_ids]
        candidate = e._candidate_repo.create_candidate(  # noqa: SLF001
            experiment_id=e._experiment_id,  # noqa: SLF001
            task_id=task_name,
            generation=generation,
            artifact_hash=artifact_hash,
            search_policy_id=e._champion_policy_id,  # noqa: SLF001
            island_id=island_id,
            parents=parents_with_relation or None,
            meta={"thought": thought.thought[:500], "relation": relation, "model": model},
        )
        e._total_candidates += 1  # noqa: SLF001

        # 向量 Outbox
        e._enqueue_vector_index("candidate", candidate.id, artifact_hash)  # noqa: SLF001

        # 记录思想
        thought_record = e._candidate_repo.create_thought(  # noqa: SLF001
            experiment_id=e._experiment_id,  # noqa: SLF001
            task_id=task_name,
            content=thought.thought,
            rationale=thought.rationale,
            risk_notes=thought.risk_notes,
            confidence=thought.confidence,
            mechanism_tags=thought.mechanism_tags,
        )
        thought_hash = e._artifact_store.store_text(thought.thought, "log")  # noqa: SLF001
        e._enqueue_vector_index("thought", thought_record.id, thought_hash)  # noqa: SLF001

        # Reference edges
        e._write_reference_edges(candidate.id, inspiration, parent_ids=parent_ids)  # noqa: SLF001

        # MCTS 扩展
        if parent_ids:
            e._mcts.expand(parent_ids[0], [(candidate.id, thought.confidence)])  # noqa: SLF001
        else:
            e._mcts.add_node(candidate.id, parent=None, prior=thought.confidence)  # noqa: SLF001

        # 步骤 9-11: 评估
        output = self.evaluate_candidate(candidate.id, artifact_hash)
        e._island_manager.assign_candidate(candidate.id, island_id)  # noqa: SLF001

        # Router 奖励更新
        if e._router is not None and model and output is not None:  # noqa: SLF001
            self._update_router_reward(model, output, parent_ids)

        return candidate.id, artifact_hash

    def evaluate_candidate(
        self,
        candidate_id: str,
        artifact_hash: str,
    ) -> EvalOutput | None:
        """评估候选（步骤 9-11）+ 记录 evaluation_run."""
        e = self._e

        candidate_artifact = CandidateArtifact(
            candidate_id=candidate_id,
            source_hash=artifact_hash,
            manifest_hash=None,
            language="python",
        )
        eval_context = EvaluationContext(
            experiment_id=e._experiment_id,  # noqa: SLF001
            evaluator_version_id=e._evaluator_version_id,  # noqa: SLF001
            environment_version_id=e._environment_version_id,  # noqa: SLF001
        )

        # 创建评估运行记录
        try:
            run = e._eval_repo.create(  # noqa: SLF001
                experiment_id=e._experiment_id,  # noqa: SLF001
                candidate_id=candidate_id,
                evaluator_version_id=e._evaluator_version_id,  # noqa: SLF001
                environment_version_id=e._environment_version_id,  # noqa: SLF001
            )
            e._eval_repo.start(run.id)  # noqa: SLF001
        except StorageError:
            logger.debug("Could not create evaluation_run record", exc_info=True)
            run = None

        # 步骤 9: build_plan
        try:
            plan = e._task_evaluator.build_plan(candidate_artifact, eval_context)  # noqa: SLF001
        except EvaluatorError:
            logger.exception("Failed to build plan for %s", candidate_id)
            if run:
                e._eval_repo.fail(run.id, "build_plan error")  # noqa: SLF001
            return None

        # 步骤 10: sandbox 执行
        policy = SandboxPolicy(
            timeout_sec=e._config.sandbox_timeout,  # noqa: SLF001
            mem_limit_mb=e._config.sandbox_mem_limit_mb,  # noqa: SLF001
        )
        try:
            result = e._sandbox.execute(plan, candidate_artifact, policy)  # noqa: SLF001
        except SandboxError:
            logger.exception("Sandbox execution failed for %s", candidate_id)
            if run:
                e._eval_repo.fail(run.id, "sandbox execution error")  # noqa: SLF001
            return None

        # 步骤 11: parse + 更新状态
        output = e._task_evaluator.parse_result(result, eval_context)  # noqa: SLF001

        # 完成评估运行记录
        if run:
            try:
                e._eval_repo.complete(  # noqa: SLF001
                    run.id,
                    passed=output.passed,
                    primary_score=output.score,
                    metrics=output.metrics,
                    execution_time_ms=result.execution_time_ms,
                    memory_peak_kb=result.memory_peak_kb,
                    cpu_time_ms=result.cpu_time_ms,
                )
            except StorageError:
                logger.debug("Could not complete evaluation_run record", exc_info=True)

        # 更新 candidate 状态
        e._candidate_repo.update_status(candidate_id, "evaluated" if output.passed else "failed")  # noqa: SLF001

        # 更新 best
        if output.passed:
            e._update_best(candidate_id, output.score)  # noqa: SLF001

        # 记录分数供 Slow Loop
        e._recent_scores.append(output.score)  # noqa: SLF001

        # meta-scratchpad
        thought_text = ""
        cand_meta = e._candidate_repo.get_candidate(candidate_id)  # noqa: SLF001
        if cand_meta and cand_meta.meta:
            thought_text = cand_meta.meta.get("thought", "")
        e._update_meta_scratchpad(thought_text, output.score)  # noqa: SLF001

        # MCTS 回传
        e._mcts.backpropagate(candidate_id, output.score)  # noqa: SLF001

        # 岛屿精英更新
        island_id = e._lookup_island(candidate_id)  # noqa: SLF001
        if island_id:
            island = e._island_manager.get_island(island_id)  # noqa: SLF001
            if island:
                island.update_elite(candidate_id, output.score)
                if output.passed:
                    e._island_manager.reset_stagnation(island_id)  # noqa: SLF001
                else:
                    e._island_manager.increment_stagnation(island_id)  # noqa: SLF001

        # 搜索状态更新
        e._candidate_repo.update_search_state(  # noqa: SLF001
            candidate_id,
            visit_delta=1,
            value_delta=output.score,
            frontier_status="elite" if output.passed else "closed",
        )

        # 成功记忆
        if output.passed:
            e._memory_store.add_memory(  # noqa: SLF001
                scope_level=1,
                outcome_summary={
                    "candidate_id": candidate_id,
                    "score": output.score,
                    "metrics": output.metrics,
                },
                success_flag=True,
                experiment_id=e._experiment_id,  # noqa: SLF001
                candidate_id=candidate_id,
            )

        # 预算记账
        e._budget_guard.consume(  # noqa: SLF001
            model="sandbox",
            input_tokens=0,
            output_tokens=0,
            compute_sec=result.execution_time_ms / 1000,
        )

        return output

    def _update_router_reward(
        self,
        model: str,
        output: EvalOutput,
        parent_ids: list[str],
    ) -> None:
        """Router 奖励更新（ShinkaEvolve 相对奖励公式，T3: 批量查询）."""
        from omnievolve.agents.router import compute_shinka_reward

        e = self._e

        parent_score = 0.0
        if parent_ids:
            placeholders = ",".join(["?"] * len(parent_ids))
            score_rows = e._db.fetchall(  # noqa: SLF001
                f"""
                SELECT candidate_id, MAX(primary_score) as score
                FROM evaluation_run
                WHERE candidate_id IN ({placeholders})
                  AND status = 'completed' AND passed = 1
                GROUP BY candidate_id
                """,
                tuple(parent_ids),
            )
            parent_scores = [r["score"] for r in score_rows if r["score"]]
            parent_score = max(parent_scores) if parent_scores else 0.0

        baseline_score = e._get_baseline_score()  # noqa: SLF001
        reward = compute_shinka_reward(output.score, parent_score, baseline_score)
        assert e._router is not None  # noqa: SLF001 — guarded by caller
        e._router.update(model=model, role="coder", reward=reward)  # noqa: SLF001
