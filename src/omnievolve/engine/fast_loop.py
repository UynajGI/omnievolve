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


def _combine_failures(failures: list[str]) -> str:
    """合并多个父代的评估失败信息（P0-1）.

    取第一个非空失败（最直接的父代），避免多个失败信息淹没上下文。
    多个非空时，只保留第一个以保持 Prompt 简洁。
    """
    for f in failures:
        if f and f.strip():
            return f.strip()[:1000]  # 硬截断防止超长 stderr 撑爆 token budget
    return ""


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

        # P1-3: 强制反向传播（后期加速收敛，跳过完整进化链）
        if parent_ids and e._mcts.should_force_backprop():  # noqa: SLF001
            e._mcts.force_backprop(parent_ids[0])  # noqa: SLF001
            # 持久化到 candidate_search_state
            e._candidate_repo.update_search_state(parent_ids[0], visit_delta=1)  # noqa: SLF001
            logger.debug("P1-3: forced backprop on %s", parent_ids[0])
            return None, ""

        # 加载父代代码 / 思想 / 评估失败信息（P0-1: 反馈闭环）
        parent_codes, parent_thoughts, parent_failures = e._load_parents(parent_ids)  # noqa: SLF001

        # 步骤 1: Router 选择模型
        model = e._select_model(generation)  # noqa: SLF001

        # 1.3/2.2: 计算停滞等级（供融合路由 + scope 检索 + AgentContext 复用）
        stagnation_level = self._compute_stagnation_level(island_id)

        # 步骤 3/可选 crossover
        base_code: str | None = None
        if relation == "crossover" and len(parent_codes) >= 2:
            base_code = e._crossover.combine(parent_codes, strategy="segment")  # noqa: SLF001

        # 2.2: 停滞触发 LLM 语义融合（替代机械 crossover）
        if (
            stagnation_level >= 2
            and e._config.fusion_mode == "llm"  # noqa: SLF001
            and parent_codes
        ):
            try:
                from omnievolve.agents.fusion import FusionAgent

                fusion_agent = FusionAgent(e._llm)  # noqa: SLF001
                # 从其他 island 收集高分参考
                references = e._collect_inspiration_programs(parent_ids, top_k=2)  # noqa: SLF001
                if references:
                    fused = fusion_agent.fuse(
                        parent_codes[0],
                        references,
                        experiment_id=e._experiment_id,  # noqa: SLF001
                    )
                    if fused.full_code.strip():
                        base_code = fused.full_code
                        logger.debug("2.2: LLM fusion applied (stagnation=%d)", stagnation_level)
            except Exception:
                logger.debug("LLM fusion failed, falling back to mechanical", exc_info=True)

        # 检索记忆
        # 1.3: 根据停滞等级决定 scope 范围（正常→L0+L1，停滞→全域检索）
        scope_levels = [0, 1] if stagnation_level == 0 else [0, 1, 2, 3, 4]
        memory_hits = e._memory_store.retrieve(  # noqa: SLF001
            experiment_id=e._experiment_id,  # noqa: SLF001
            task_id=task_name,
            success_only=True,
            scope_levels=scope_levels,
            limit=e._search_policy.retrieval_budget,  # noqa: SLF001
        )

        # Step 2: 向量语义重排序（有 HybridRetriever 时）
        if e._hybrid_retriever and parent_thoughts:  # noqa: SLF001
            try:
                query_text = parent_thoughts[0][:500]
                vector_hits = e._hybrid_retriever.search_memory(  # noqa: SLF001
                    query_text,
                    experiment_id=e._experiment_id,  # noqa: SLF001
                    top_k=e._search_policy.retrieval_budget,  # noqa: SLF001
                )
                if vector_hits:
                    vector_order = {h["id"]: i for i, h in enumerate(vector_hits)}
                    memory_hits.sort(key=lambda m: vector_order.get(m.id, 999))
            except Exception:
                pass  # 向量不可用时保持 SQL 排序

        # Step 5a: 记录 citation（记忆被检索并用于 prompt）
        for m in memory_hits:
            try:
                e._memory_store.record_citation(m.id)  # noqa: SLF001
            except Exception:
                pass
        # P2-3: 记忆格式化增强（含 score + diff 摘要 + outcome）
        memory_summaries = []
        for m in memory_hits:
            score_str = ""
            if isinstance(m.outcome_summary, dict):
                score_str = f"score={m.outcome_summary.get('score', '?')}"
            # 加载 code_diff_hash 对应的 diff 内容
            diff_text = ""
            if m.code_diff_hash:
                try:
                    raw = e._artifact_store.load_text(m.code_diff_hash)  # noqa: SLF001
                    diff_text = raw[:200] if raw else ""
                except Exception:
                    pass
            outcome_text = str(m.outcome_summary)[:150]
            parts = [f"[L{m.scope_level}/{'SUCCESS' if m.success_flag else 'FAIL'}] {score_str}"]
            if diff_text:
                parts.append(f"改动: {diff_text}")
            parts.append(f"效果: {outcome_text}")
            memory_summaries.append(
                {
                    "outcome_summary": " → ".join(parts),
                    "scope_level": m.scope_level,
                    "success": m.success_flag,
                }
            )

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

        # Step 4: Director RAG — 语义相关的历史 thought
        rag_context: list[dict] = []
        if e._hybrid_retriever and parent_thoughts:  # noqa: SLF001
            try:
                rag_context = e._hybrid_retriever.search_thoughts(  # noqa: SLF001
                    parent_thoughts[0][:300],
                    experiment_id=e._experiment_id,  # noqa: SLF001
                    top_k=3,
                )
            except Exception:
                pass

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
            # P0-1: 注入父代评估失败信息到 Coder 上下文
            last_eval_failure=_combine_failures(parent_failures),
            # P2-1: 停滞等级（根据岛屿停滞计数自动升级）
            stagnation_level=stagnation_level,
            # P2-2: 兄弟节点摘要
            sibling_summaries=self._load_sibling_summaries(island_id, generation),
            # Step 4: 向量 RAG 检索结果
            rag_context=rag_context,
            search_policy_id=e._champion_policy_id,  # noqa: SLF001
            evaluator_version_id=e._evaluator_version_id,  # noqa: SLF001
            environment_version_id=e._environment_version_id,  # noqa: SLF001
            model=model,
            prompt_version_id=e._load_champion_prompt("director"),  # noqa: SLF001
        )

        # 步骤 4: Director
        thought = e._director.evolve_thought(ctx)  # noqa: SLF001

        # 步骤 5: NoveltyGate — Step 3: 注入向量相似度
        existing_sims: list[float] = []
        if e._hybrid_retriever:  # noqa: SLF001
            try:
                _, max_sim = e._hybrid_retriever.check_novelty(  # noqa: SLF001
                    thought.thought,
                    collection="thought_default",
                    threshold=e._config.novelty_threshold,  # noqa: SLF001
                )
                if max_sim > 0:
                    existing_sims = [max_sim]
            except Exception:
                pass

        novelty_result = e._novelty_gate.check(  # noqa: SLF001
            thought=thought.thought,
            code=base_code,
            existing_similarities=existing_sims or None,
        )
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

        # P0-2: Critic 审查时注入上一轮执行失败信息
        critic_stderr = ctx.last_eval_failure
        passed, _ = e._critic.review(code, thought, last_eval_stderr=critic_stderr)  # noqa: SLF001
        retries = 0
        while not passed and retries < e._config.novelty_retry_limit:  # noqa: SLF001
            retries += 1
            code = e._coder.generate_code(ctx, thought)  # noqa: SLF001
            passed, _ = e._critic.review(code, thought, last_eval_stderr=critic_stderr)  # noqa: SLF001

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

        # Step 5b: 记录 adoption（记忆被成功候选“采用”）
        if output is not None and output.passed and memory_hits:
            try:
                e._memory_store.record_adoption(memory_hits[0].id)  # noqa: SLF001
            except Exception:
                pass

        # Router 奖励更新
        if e._router is not None and model and output is not None:  # noqa: SLF001
            self._update_router_reward(model, output, parent_ids)

        return candidate.id, artifact_hash

    def evaluate_candidate(
        self,
        candidate_id: str,
        artifact_hash: str,
    ) -> EvalOutput | None:
        """评估候选（步骤 9-11）+ 记录 evaluation_run.

        Phase 3: 支持渐进式评估（Stage 0→3，任一阶段失败则 early-exit）。
        """
        e = self._e

        # Phase 3: 渐进式评估路径
        if e._config.progressive_eval_enabled:  # noqa: SLF001
            build_stage = getattr(e._task_evaluator, "build_stage_plan", None)  # noqa: SLF001
            if build_stage is not None:
                return self._evaluate_progressive(candidate_id, artifact_hash)

        # 默认全量评估路径
        return self._evaluate_full(candidate_id, artifact_hash)

    def _evaluate_progressive(
        self,
        candidate_id: str,
        artifact_hash: str,
    ) -> EvalOutput | None:
        """渐进式评估：Stage 0→3，任一阶段失败则 early-exit."""
        from omnievolve.eval.plan_validator import EvaluationStage

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
        policy = SandboxPolicy(
            timeout_sec=e._config.sandbox_timeout,  # noqa: SLF001
            mem_limit_mb=e._config.sandbox_mem_limit_mb,  # noqa: SLF001
        )

        output: EvalOutput | None = None
        for stage in EvaluationStage:
            # 尝试获取阶段特定计划，回退到默认 build_plan
            build_stage = getattr(e._task_evaluator, "build_stage_plan", None)  # noqa: SLF001
            plan = (
                build_stage(candidate_artifact, eval_context, stage.value) if build_stage else None
            )
            if plan is None:
                plan = e._task_evaluator.build_plan(candidate_artifact, eval_context)  # noqa: SLF001

            try:
                result = e._sandbox.execute(plan, candidate_artifact, policy)  # noqa: SLF001
            except SandboxError:
                logger.debug("Progressive eval stage %d failed for %s", stage.value, candidate_id)
                return EvalOutput(
                    score=0.0,
                    metrics={},
                    passed=False,
                    failure_reason=f"Stage {stage.value} sandbox error",
                )

            output = e._task_evaluator.parse_result(result, eval_context)  # noqa: SLF001

            # Early-exit: 非最终阶段失败则提前终止
            if not output.passed and stage < EvaluationStage.STAGE_3_BENCHMARK:
                logger.debug(
                    "Progressive eval early-exit at stage %d for %s",
                    stage.value,
                    candidate_id,
                )
                break

        # 更新候选状态（复用全量评估的后处理逻辑）
        if output:
            e._candidate_repo.update_status(  # noqa: SLF001
                candidate_id, "evaluated" if output.passed else "failed"
            )
            if output.passed:
                e._update_best(candidate_id, output.score)  # noqa: SLF001
            e._recent_scores.append(output.score)  # noqa: SLF001
            e._mcts.backpropagate(candidate_id, output.score)  # noqa: SLF001

        return output

    def _evaluate_full(
        self,
        candidate_id: str,
        artifact_hash: str,
    ) -> EvalOutput | None:
        """全量评估（原有逻辑）."""
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

        # Phase 4.4: 创建 Job 记录（支持 kill -9 恢复）
        job = None
        try:
            job = e._job_store.create_job(  # noqa: SLF001
                experiment_id=e._experiment_id,  # noqa: SLF001
                job_type="evaluate_candidate",
                payload={"candidate_id": candidate_id, "artifact_hash": artifact_hash},
            )
        except Exception:
            logger.debug("Could not create job record", exc_info=True)

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
            if job:
                try:
                    e._job_store.fail_job(job.id, "sandbox execution error")  # noqa: SLF001
                except Exception:
                    pass
            return None

        # 步骤 11: parse + 更新状态
        output = e._task_evaluator.parse_result(result, eval_context)  # noqa: SLF001

        # Epiplexity 辅助适应度: fitness = f_task + β * S_φ(code)
        # β 来自 SearchPolicyGenome，可被 Slow Loop 自进化
        beta = getattr(e._search_policy, "epiplexity_beta", 0.0)  # noqa: SLF001
        if beta > 0 and output.passed:
            try:
                from omnievolve.engine.epiplexity import EpiplexityEstimator

                if e._epiplexity_est is None:  # noqa: SLF001
                    e._epiplexity_est = EpiplexityEstimator()  # noqa: SLF001
                code_text = e._artifact_store.load_text(artifact_hash)  # noqa: SLF001
                epi_score = e._epiplexity_est.score(code_text) if code_text else 0.0  # noqa: SLF001
                # 混合计分（不超过 1.0）
                blended = min(output.score + beta * epi_score, 1.0)
                output = EvalOutput(
                    score=blended,
                    metrics={**output.metrics, "epiplexity": epi_score, "task_score": output.score},
                    passed=output.passed,
                    failure_reason=output.failure_reason,
                )
            except Exception:
                logger.debug("Epiplexity scoring failed for %s", artifact_hash, exc_info=True)

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

        # Phase 4: 数据泄漏检测（高分候选自动触发）
        if output.passed and output.score > 0.9 and getattr(e, "_leakage_detector", None):  # noqa: SLF001
            try:
                code_text = e._artifact_store.load_text(artifact_hash)  # noqa: SLF001
                baseline = e._get_baseline_score()  # noqa: SLF001
                leak_result = e._leakage_detector.check(  # noqa: SLF001
                    code_text or "", "", output.score, baseline
                )
                if leak_result.has_leakage and leak_result.confidence == "high":
                    logger.warning("Data leakage detected: %s", leak_result.reason)
                    output = type(output)(
                        score=output.score * 0.5,
                        metrics={**output.metrics, "leakage_penalty": True},
                        passed=True,
                        failure_reason=f"Leakage suspect: {leak_result.reason}",
                    )
            except Exception:
                logger.debug("Leakage check failed, skipping", exc_info=True)

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

        # Phase 4.4: 完成 Job 记录
        if job:
            try:
                e._job_store.complete_job(job.id, result_ref=artifact_hash)  # noqa: SLF001
            except Exception:
                pass

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

    def _compute_stagnation_level(self, island_id: str) -> int:
        """P2-1: 计算停滞等级.

        根据岛屿停滞计数与 max_stagnation_gens 的比值升级：
        - 0: 正常（未停滞）
        - 1: 停滞 >= 1x max_stagnation_gens（提示 Tier 2）
        - 2: 停滞 >= 2x max_stagnation_gens（强制 Tier 2）
        - 3: 停滞 >= 3x max_stagnation_gens（强制 Tier 3 范式转变）
        """
        e = self._e
        island = e._island_manager.get_island(island_id)  # noqa: SLF001
        if island is None:
            return 0
        threshold = e._config.max_stagnation_gens  # noqa: SLF001
        if threshold <= 0:
            return 0
        count = island.stagnation_count
        if count >= threshold * 3:
            return 3
        if count >= threshold * 2:
            return 2
        if count >= threshold:
            return 1
        return 0

    def _load_sibling_summaries(self, island_id: str, generation: int) -> list[str]:
        """P2-2: 加载兄弟节点摘要（同一 island，最近 2 代）."""
        import json

        e = self._e
        try:
            rows = e._db.fetchall(  # noqa: SLF001
                """
                SELECT c.id, c.generation, c.meta
                FROM candidate c
                WHERE c.experiment_id = ?
                  AND c.island_id = ?
                  AND c.generation >= ?
                ORDER BY c.generation DESC, c.created_at DESC
                LIMIT 5
                """,
                (e._experiment_id, island_id, max(0, generation - 2)),  # noqa: SLF001
            )
            summaries = []
            for row in rows:
                raw_meta = row["meta"]
                meta = json.loads(raw_meta) if isinstance(raw_meta, str) and raw_meta else {}
                thought = meta.get("thought", "")[:200] if meta else ""
                if thought:
                    summaries.append(f"[gen {row['generation']}] {thought}")
            return summaries[:3]
        except Exception:
            logger.debug("Failed to load sibling summaries", exc_info=True)
            return []
