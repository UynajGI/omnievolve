"""Fast Loop Step — 提取自 EvolutionEngine.

T1 重构第三步：将 _evolve_one + _evaluate_candidate 提取为独立组件。
使用 "method object" 模式：引擎作为数据持有者，控制流移到此类。

Phase 3: prepare/commit 拆分 — 支持异步并行流水线。
prepare() 执行无共享状态变更的步骤（LLM + sandbox），
commit_result() 串行执行所有共享状态更新（MCTS/best/router/island）。
"""

from __future__ import annotations

import logging
from contextlib import nullcontext
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from omnievolve.agents.base import AgentContext, CodeOutput, ThoughtOutput
from omnievolve.engine.novelty import NoveltyDecision, NoveltyResult
from omnievolve.engine.operator_portfolio import OperatorDecision
from omnievolve.eval.task_evaluator import (
    CandidateArtifact,
    EvalOutput,
    EvaluationContext,
)
from omnievolve.exceptions import (
    EvaluatorError,
    EvolutionError,
    SandboxError,
    StorageError,
)
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
            return f.strip()[:1000]  # 硬截断防止超长 stderr 撇爆 token budget
    return ""


@dataclass
class PreparedCandidate:
    """Phase 3: prepare() 的返回值 — 包含所有评估产物，不含状态变更.

    prepare() 执行步骤 1-10（parent→Director→Coder→Critic→sandbox eval），
    commit_result() 执行步骤 11（MCTS/best/router/island 状态更新）。
    """

    candidate_id: str
    artifact_hash: str
    output: EvalOutput | None
    parent_ids: list[str]
    model: str
    island_id: str
    manifest_hash: str | None = None
    thought_confidence: float = 1.0
    critic_passed: bool = True
    generation: int = 0
    thought_summary: str = ""
    mechanism_tags: list = field(default_factory=list)
    # 评估上下文（供 commit 使用）
    eval_run_id: str | None = None
    job_id: str | None = None
    sandbox_result: Any = None
    memory_hits: list = field(default_factory=list)
    reference_ids: list[str] = field(default_factory=list)
    role_models: dict[str, str] = field(default_factory=dict)
    role_calls: set[str] = field(default_factory=set)
    idea_novelty: NoveltyResult | None = None
    candidate_novelty: NoveltyResult | None = None
    operator_decision: OperatorDecision | None = None


class FastLoopStep:
    """单个候选的完整进化链（步骤 1-11）.

    纯控制流组件 — 所有数据通过 engine 引用访问。
    """

    def __init__(self, engine: EvolutionEngine) -> None:
        self._e = engine

    def _prof_step(self, name: str, generation: int = 0) -> Any:
        """零开销 profiling hook: profiler=None 时返回 nullcontext."""
        profiler = getattr(self._e, "_profiler", None)
        if profiler is None:
            return nullcontext()
        return profiler.step(name, generation=generation)

    def evolve_one(
        self,
        generation: int,
        task_name: str,
        island_id: str,
        *,
        slot: int = 0,
    ) -> tuple[str | None, str]:
        """执行单个候选的完整进化链（步骤 1-11）.

        纯委托: prepare() 执行步骤 1-10（LLM + sandbox），
        commit_result() 执行步骤 11（串行状态更新）。
        """
        prepared = self.prepare(generation, task_name, island_id, slot=slot)
        if prepared is None:
            return None, ""
        return self.commit_result(prepared)

    def prepare(
        self,
        generation: int,
        task_name: str,
        island_id: str,
        *,
        slot: int = 0,
    ) -> PreparedCandidate | None:
        """Phase 3: 步骤 1-10 — 可并行执行，无共享状态变更.

        执行完整的 LLM + sandbox 流程，但不做 MCTS expand/island assign/router update。
        返回 PreparedCandidate，供 commit_result() 做串行状态合并。
        """
        e = self._e
        stagnation_level = self._compute_stagnation_level(island_id)
        operator_decision = None
        if (
            e._operator_portfolio is not None  # noqa: SLF001
            and not e._config.random_search_mode  # noqa: SLF001
        ):
            island = e._island_manager.get_island(island_id)  # noqa: SLF001
            eligible = ["point", "diff", "rewrite"]
            if island is not None and len(island.elite_archive) >= 2:
                eligible.append("crossover")
            if stagnation_level > 0:
                eligible.append("repair")
            stage = (
                "deep_stagnation"
                if stagnation_level >= 2
                else "stagnant"
                if stagnation_level
                else "normal"
            )
            operator_decision = e._operator_portfolio.select(  # noqa: SLF001
                task=task_name,
                stage=stage,
                eligible=eligible,
            )

        # 步骤 2: 选择父代
        with self._prof_step("select_parents", generation):
            if e._config.random_search_mode:  # noqa: SLF001
                baseline = e._db.fetchone(  # noqa: SLF001
                    "SELECT baseline_candidate_id FROM experiment WHERE id = ?",
                    (e._experiment_id,),  # noqa: SLF001
                )
                baseline_id = baseline["baseline_candidate_id"] if baseline else None
                parent_ids = [str(baseline_id)] if baseline_id else []
                relation = "mutate"
            else:
                parent_ids, relation = e._select_parents(  # noqa: SLF001
                    island_id,
                    preferred_operator=(
                        operator_decision.operator if operator_decision is not None else ""
                    ),
                )

        # P1-3: 强制反向传播
        if (
            not e._config.random_search_mode  # noqa: SLF001
            and parent_ids
            and e._mcts.should_force_backprop()  # noqa: SLF001
        ):
            e._mcts.force_backprop(parent_ids[0])  # noqa: SLF001
            e._candidate_repo.update_search_state(parent_ids[0], visit_delta=1)  # noqa: SLF001
            return None

        parent_codes, parent_thoughts, parent_failures = e._load_parents(parent_ids)  # noqa: SLF001
        director_model = (
            ""
            if e._config.random_search_mode or e._config.single_agent_mode  # noqa: SLF001
            else e._select_model(  # noqa: SLF001
                generation,
                "director",
                stagnation_level=float(stagnation_level),
            )
        )

        # 步骤 3/可选 crossover + fusion
        base_code = None
        if relation == "crossover" and len(parent_codes) >= 2:
            base_code = e._crossover.combine(parent_codes, strategy="semantic")  # noqa: SLF001
        if (
            (relation == "crossover" or stagnation_level >= 2)
            and e._config.fusion_mode == "llm"  # noqa: SLF001
            and parent_codes
        ):
            try:
                from omnievolve.agents.fusion import FusionAgent

                fusion_agent = FusionAgent(e._llm)  # noqa: SLF001
                references = e._collect_inspiration_programs(parent_ids, top_k=2)  # noqa: SLF001
                if references:
                    fused = fusion_agent.fuse(
                        parent_codes[0], references, experiment_id=e._experiment_id
                    )  # noqa: SLF001
                    if fused:
                        base_code = fused.full_code
            except Exception:
                logger.debug("LLM fusion failed, falling back to mechanical", exc_info=True)

        # 记忆检索 + 向量重排序
        scope_levels = [0, 1] if stagnation_level == 0 else [0, 1, 2, 3, 4]
        memory_hits = e._memory_store.retrieve(  # noqa: SLF001
            experiment_id=e._experiment_id,
            task_id=task_name,  # noqa: SLF001
            success_only=True,
            scope_levels=scope_levels,
            limit=e._search_policy.retrieval_budget,  # noqa: SLF001
        )
        if e._hybrid_retriever and parent_thoughts:  # noqa: SLF001
            try:
                vector_hits = e._hybrid_retriever.search_memory(  # noqa: SLF001
                    parent_thoughts[0][:500],
                    experiment_id=e._experiment_id,  # noqa: SLF001
                    top_k=e._search_policy.retrieval_budget,  # noqa: SLF001
                )
                if vector_hits:
                    vector_order = {h["id"]: i for i, h in enumerate(vector_hits)}
                    memory_hits.sort(key=lambda m: vector_order.get(m.id, 999))
            except Exception:
                logger.debug("Vector memory rerank failed, keeping SQL order", exc_info=True)
        for m in memory_hits:
            try:
                e._memory_store.record_citation(m.id)  # noqa: SLF001
            except Exception:
                logger.debug("Memory citation recording failed", exc_info=True)
        # P2-3 formatting
        memory_summaries = []
        for m in memory_hits:
            score_str = ""
            if isinstance(m.outcome_summary, dict):
                score_str = f"score={m.outcome_summary.get('score', '?')}"
            diff_text = ""
            if m.code_diff_hash:
                try:
                    raw = e._artifact_store.load_text(m.code_diff_hash)  # noqa: SLF001
                    diff_text = raw[:200] if raw else ""
                except Exception:
                    logger.debug("Failed to load diff for memory %s", m.id, exc_info=True)
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

        inspiration = e._collect_inspiration_programs(parent_ids)  # noqa: SLF001
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

        reference_ids = list(
            dict.fromkeys(
                str(program["candidate_id"])
                for program in inspiration
                if program.get("candidate_id") and program["candidate_id"] not in parent_ids
            )
        )
        if e._config.random_search_mode:  # noqa: SLF001
            inspiration = [program for program in inspiration if program.get("is_parent")]
            memory_hits = []
            reference_ids = []

        # Director RAG
        rag_context = []
        if e._hybrid_retriever and parent_thoughts:  # noqa: SLF001
            try:
                rag_context = e._hybrid_retriever.search_thoughts(  # noqa: SLF001
                    parent_thoughts[0][:300],
                    experiment_id=e._experiment_id,
                    top_k=3,  # noqa: SLF001
                )
            except Exception:
                logger.debug("Director RAG search failed", exc_info=True)

        ctx = AgentContext(
            experiment_id=e._experiment_id,
            task_id=task_name,  # noqa: SLF001
            generation=generation,
            island_id=island_id,
            parent_candidate_ids=parent_ids,
            parent_thoughts=parent_thoughts,
            parent_artifact_hashes=[],
            inspiration_programs=inspiration,
            memory_hits=memory_summaries,
            meta_scratchpad=e._meta_scratchpad,  # noqa: SLF001
            last_eval_failure=_combine_failures(parent_failures),
            stagnation_level=stagnation_level,
            sibling_summaries=self._load_sibling_summaries(island_id, generation),
            rag_context=rag_context,
            search_policy_id=e._champion_policy_id,  # noqa: SLF001
            evaluator_version_id=e._evaluator_version_id,  # noqa: SLF001
            environment_version_id=e._environment_version_id,  # noqa: SLF001
            model=director_model,
            generation_mode=(operator_decision.operator if operator_decision is not None else ""),
            prompt_version_id=e._load_champion_prompt("director"),  # noqa: SLF001
        )

        # 步骤 4: Director
        if e._config.random_search_mode:  # noqa: SLF001
            thought = ThoughtOutput(
                thought="Apply one task-agnostic random AST mutation.",
                rationale="LLM-free random-search baseline",
                confidence=0.0,
                mechanism_tags=["random_search"],
            )
        elif e._config.single_agent_mode:  # noqa: SLF001
            thought = ThoughtOutput(
                thought=(
                    "Act as the sole optimization agent. Improve the parent program "
                    "directly using the task context and evaluation feedback."
                ),
                rationale="single-agent ablation",
                confidence=0.5,
                mechanism_tags=["single_agent"],
            )
        else:
            with self._prof_step("director", generation):
                thought = e._director.evolve_thought(ctx)  # noqa: SLF001
        role_calls: set[str] = set()
        role_models: dict[str, str] = {}
        if director_model and not (
            e._config.random_search_mode or e._config.single_agent_mode  # noqa: SLF001
        ):
            role_calls.add("director")
            role_models["director"] = director_model

        # 步骤 5a: idea novelty — only the mechanism/thought is checked here.
        idea_novelty = None
        if e._config.novelty_enabled:  # noqa: SLF001
            with self._prof_step("idea_novelty", generation):
                existing_sims = []
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
                        logger.debug("Novelty vector check failed", exc_info=True)
                idea_novelty = e._novelty_gate.check_idea(  # noqa: SLF001
                    thought.thought,
                    existing_similarities=existing_sims or None,
                )
        if idea_novelty is not None and idea_novelty.decision == NoveltyDecision.REJECT:
            e._mcts.rollback_last_select()  # noqa: SLF001
            return None

        # 步骤 6: Coder + Critic
        coder_model = ""
        critic_model = ""
        if e._config.random_search_mode:  # noqa: SLF001
            from omnievolve.engine.random_search import (
                derive_random_search_seed,
                mutate_randomly,
            )

            source = base_code or (parent_codes[0] if parent_codes else "")
            if not source.strip():
                raise EvolutionError("random search requires an initial parent program")
            mutation_seed = derive_random_search_seed(
                experiment_seed=e._config.seed,  # noqa: SLF001
                generation=generation,
                slot=slot,
                island_id=island_id,
                parent_code=source,
            )
            mutation = mutate_randomly(source, seed=mutation_seed)
            code = CodeOutput(
                diff=mutation.description,
                full_code=mutation.code,
                explanation=(f"LLM-free random-search mutation (seed={mutation.seed})"),
            )
            passed = True
        else:
            coder_model = e._select_model(  # noqa: SLF001
                generation,
                "coder",
                stagnation_level=float(stagnation_level),
                novelty_deficit=(
                    idea_novelty.similarity_score if idea_novelty is not None else 0.0
                ),
            )
            coder_ctx = replace(
                ctx,
                model=coder_model,
                prompt_version_id=e._load_champion_prompt("coder"),  # noqa: SLF001
            )
            with self._prof_step("coder", generation):
                code = e._coder.generate_code(coder_ctx, thought)  # noqa: SLF001
                if coder_model:
                    role_calls.add("coder")
                    role_models["coder"] = coder_model
                if not code.full_code.strip():
                    if base_code:
                        code = type(code)(
                            diff="", full_code=base_code, explanation="crossover baseline"
                        )
                    elif parent_codes:
                        code = type(code)(
                            diff="",
                            full_code=parent_codes[0],
                            explanation="fallback to parent code",
                        )

            with self._prof_step("critic", generation):
                critic_stderr = ctx.last_eval_failure
                if getattr(e._critic, "_llm", None) is not None:  # noqa: SLF001
                    critic_model = e._select_model(  # noqa: SLF001
                        generation,
                        "critic",
                        stagnation_level=float(stagnation_level),
                    )

                def review_current() -> tuple[bool, str]:
                    review_with_trace = getattr(e._critic, "review_with_trace", None)  # noqa: SLF001
                    if review_with_trace is None:
                        return e._critic.review(  # noqa: SLF001
                            code, thought, last_eval_stderr=critic_stderr
                        )
                    trace = review_with_trace(
                        code,
                        thought,
                        last_eval_stderr=critic_stderr,
                        model=critic_model or None,
                    )
                    if trace.llm_used and trace.model:
                        role_calls.add("critic")
                        role_models["critic"] = trace.model
                    return trace.passed, trace.feedback

                passed, _ = review_current()
                retries = 0
                while not passed and retries < e._config.novelty_retry_limit:  # noqa: SLF001
                    retries += 1
                    code = e._coder.generate_code(coder_ctx, thought)  # noqa: SLF001
                    if coder_model:
                        role_calls.add("coder")
                    passed, _ = review_current()

        # 步骤 5b: candidate novelty — final code after all Coder/repair attempts.
        candidate_novelty = None
        if e._config.novelty_enabled:  # noqa: SLF001
            with self._prof_step("candidate_novelty", generation):
                code_similarities = []
                if e._hybrid_retriever:  # noqa: SLF001
                    try:
                        _, max_code_sim = e._hybrid_retriever.check_novelty(  # noqa: SLF001
                            code.full_code,
                            collection="code_default",
                            threshold=e._config.novelty_threshold,  # noqa: SLF001
                        )
                        if max_code_sim > 0:
                            code_similarities = [max_code_sim]
                    except Exception:
                        logger.debug("Candidate novelty vector check failed", exc_info=True)
                candidate_novelty = e._novelty_gate.check_candidate(  # noqa: SLF001
                    thought.thought,
                    code.full_code,
                    existing_similarities=code_similarities or None,
                    exact_reference_codes=parent_codes,
                )
        if candidate_novelty is not None and candidate_novelty.decision == NoveltyDecision.REJECT:
            e._mcts.rollback_last_select()  # noqa: SLF001
            return None

        model = "random-search" if e._config.random_search_mode else coder_model  # noqa: SLF001

        novelty_meta: dict[str, object] = {}
        if idea_novelty is not None:
            novelty_meta.update(idea_novelty.to_metrics())
        if candidate_novelty is not None:
            novelty_meta.update(candidate_novelty.to_metrics())
        candidate_meta = {
            "thought": thought.thought[:500],
            "relation": relation,
            "model": model,
            "role_models": dict(role_models),
            "operator": (operator_decision.operator if operator_decision is not None else None),
            "operator_stage": (operator_decision.stage if operator_decision is not None else None),
            **novelty_meta,
        }

        # 步骤 8: 存储代码 + 创建候选
        # CodeStore: 优先使用 store_snapshot（支持 Git ancestry）
        manifest_hash = None
        if hasattr(e._artifact_store, "store_snapshot"):  # noqa: SLF001
            from omnievolve.storage.code_store import resolve_snapshot_refs

            # CAS 优先沿用 manifest；Git 使用 commit artifact_hash。
            parent_refs = []
            for pid in parent_ids:
                prow = e._db.fetchone(  # noqa: SLF001
                    "SELECT artifact_hash, manifest_hash FROM candidate WHERE id=?",
                    (pid,),
                )
                if prow:
                    parent_refs.append(prow["manifest_hash"] or prow["artifact_hash"])
            snapshot_ref = e._artifact_store.store_snapshot(  # noqa: SLF001
                code.full_code,
                parents=parent_refs or None,
                message=thought.thought[:200],
                meta=candidate_meta,
            )
            artifact_hash, manifest_hash = resolve_snapshot_refs(  # noqa: SLF001
                e._artifact_store, snapshot_ref
            )
        else:
            artifact_hash = e._artifact_store.store_text(code.full_code, "source")  # noqa: SLF001
        parents_with_relation = [(pid, relation) for pid in parent_ids]
        candidate = e._candidate_repo.create_candidate(  # noqa: SLF001
            experiment_id=e._experiment_id,  # noqa: SLF001
            task_id=task_name,
            generation=generation,
            artifact_hash=artifact_hash,
            manifest_hash=manifest_hash,
            search_policy_id=e._champion_policy_id,  # noqa: SLF001
            island_id=island_id,
            parents=parents_with_relation or None,
            meta=candidate_meta,
        )
        e._enqueue_vector_index("candidate", candidate.id, artifact_hash)  # noqa: SLF001
        thought_record = e._candidate_repo.create_thought(  # noqa: SLF001
            experiment_id=e._experiment_id,
            task_id=task_name,  # noqa: SLF001
            content=thought.thought,
            rationale=thought.rationale,
            risk_notes=thought.risk_notes,
            confidence=thought.confidence,
            mechanism_tags=thought.mechanism_tags,
        )
        thought_hash = e._artifact_store.store_text(thought.thought, "log")  # noqa: SLF001
        e._enqueue_vector_index("thought", thought_record.id, thought_hash)  # noqa: SLF001
        e._write_reference_edges(candidate.id, inspiration, parent_ids=parent_ids)  # noqa: SLF001

        # 步骤 9-10: sandbox 执行 + 结果解析（无状态变更）
        with self._prof_step("sandbox_eval", generation):
            output, eval_run, job, sandbox_result = self._execute_sandbox(
                candidate.id,
                artifact_hash,
                manifest_hash,
                extra_metrics=novelty_meta,
            )

        return PreparedCandidate(
            candidate_id=candidate.id,
            artifact_hash=artifact_hash,
            manifest_hash=manifest_hash,
            output=output,
            parent_ids=parent_ids,
            model=model,
            island_id=island_id,
            thought_confidence=thought.confidence,
            critic_passed=passed,
            generation=generation,
            thought_summary=thought.thought,
            mechanism_tags=list(thought.mechanism_tags or []),
            eval_run_id=eval_run.id if eval_run else None,
            job_id=job.id if job else None,
            sandbox_result=sandbox_result,
            memory_hits=memory_hits,
            reference_ids=reference_ids,
            role_models=role_models,
            role_calls=role_calls,
            idea_novelty=idea_novelty,
            candidate_novelty=candidate_novelty,
            operator_decision=operator_decision,
        )

    def commit_result(self, prepared: PreparedCandidate) -> tuple[str | None, str]:
        """Phase 3: 步骤 11 — 串行执行所有共享状态变更.

        在 prepare() 并行执行后，此方法单线程串行合并结果到引擎状态。
        """
        with self._prof_step("commit", 0):
            return self._commit_inner(prepared)

    def _commit_inner(self, prepared: PreparedCandidate) -> tuple[str | None, str]:
        """commit_result 的实际实现（被 profiler 包裹）."""
        e = self._e

        # Fix 5: 计数器递增移到串行区域（避免并行 prepare 竞态）
        e._total_candidates += 1  # noqa: SLF001

        # Random-search baseline does not participate in graph search.
        search_credit_enabled = prepared.model != "random-search"
        if search_credit_enabled:
            if prepared.parent_ids:
                e._mcts.expand(
                    prepared.parent_ids[0],  # noqa: SLF001
                    [(prepared.candidate_id, prepared.thought_confidence)],
                )
            else:
                e._mcts.add_node(
                    prepared.candidate_id,
                    parent=None,  # noqa: SLF001
                    prior=prepared.thought_confidence,
                )

        # 岛屿分配
        e._island_manager.assign_candidate(prepared.candidate_id, prepared.island_id)  # noqa: SLF001

        # PR2: observer-only verifier — evaluate 后、_apply_eval_result 前。
        # 只写证据，不修改 search_score/passed/primary_score（集成计划 §9.1）。
        self._observe_verifier(prepared)

        # 应用评估结果（所有状态变更）
        if prepared.output is not None:
            self._apply_eval_result(
                prepared.candidate_id,
                prepared.artifact_hash,
                prepared.output,
                prepared.eval_run_id,
                prepared.job_id,
                prepared.sandbox_result,
                prepared.reference_ids,
                prepared.parent_ids,
                prepared.candidate_novelty,
                search_credit_enabled=search_credit_enabled,
            )

        # Step 5b: 记录 adoption
        if prepared.output is not None and prepared.output.passed and prepared.memory_hits:
            try:
                e._memory_store.record_adoption(prepared.memory_hits[0].id)  # noqa: SLF001
            except Exception:
                logger.warning("Memory adoption recording failed", exc_info=True)

        # Router 奖励更新
        if (
            search_credit_enabled
            and e._router is not None  # noqa: SLF001
            and prepared.role_calls
            and prepared.output is not None
        ):
            self._update_router_reward(
                prepared.role_models,
                prepared.role_calls,
                prepared.output,
                prepared.parent_ids,
                mechanism_novelty=(
                    prepared.idea_novelty.objective_score
                    if prepared.idea_novelty is not None
                    else 0.5
                ),
                critic_passed=prepared.critic_passed,
            )

        if e._operator_portfolio is not None and prepared.operator_decision is not None:  # noqa: SLF001
            parent_scores = [
                e._get_candidate_score(parent_id)  # noqa: SLF001
                for parent_id in prepared.parent_ids
            ]
            parent_best = (
                max(parent_scores) if parent_scores else e._get_baseline_score()  # noqa: SLF001
            )
            passed = prepared.output is not None and prepared.output.passed
            child_score = prepared.output.score if prepared.output is not None else 0.0
            e._operator_portfolio.update(  # noqa: SLF001
                prepared.operator_decision,
                relative_gain=child_score - parent_best,
                passed=passed,
            )

        return prepared.candidate_id, prepared.artifact_hash

    def _ensure_verifier_observer(self):
        """惰性构建 observer（缓存到 engine）.

        构建前执行 capability probe（§7）：不支持 logprobs 的 endpoint
        在启用前即被拒绝并留下可审计的 capability hash；未实现的 mode
        （parent_pair / island_ppt）fail fast，禁止静默退化为 observer。

        Returns:
            VerifierObserver | None — 配置关闭、无 model 或普通运行下
            probe 失败时返回 None。
        """
        e = self._e
        settings = getattr(e, "_verifier_settings", None)
        if settings is None or not settings.enabled or not settings.model:
            return None
        if e._verifier_observer is not None:  # noqa: SLF001
            return e._verifier_observer  # noqa: SLF001
        if settings.mode != "observer":
            raise ValueError(
                f"verifier mode {settings.mode!r} is not implemented; "
                "only 'observer' is available in this round (PR 1-3). "
                "parent_pair / island_ppt require the R1 gate to pass."
            )
        from omnievolve.eval.probabilistic_verifier import (
            _DEFAULT_SCORE_TOKENS,
            ProbabilisticVerifier,
            ProbabilisticVerifierConfig,
        )
        from omnievolve.eval.verification_service import VerificationService
        from omnievolve.eval.verifier_capability import VerifierCapabilityProbe
        from omnievolve.eval.verifier_observer import VerifierObserver
        from omnievolve.exceptions import LLMVerifierCapabilityError

        # capability probe：只读、启用前一次；失败按 fail_closed 分级。
        probe = VerifierCapabilityProbe(e._llm)  # noqa: SLF001
        try:
            probe_result = probe.probe(
                settings.model,
                experiment_id=e._experiment_id,  # noqa: SLF001
                prompt_version_id="verifier-observer-v1",
            )
        except LLMVerifierCapabilityError as exc:
            if settings.fail_closed_in_research:
                raise
            logger.warning("Verifier capability probe failed (%s); disabling observer", exc)
            return None
        except Exception:
            if settings.fail_closed_in_research:
                raise
            logger.warning("Verifier capability probe error; disabling observer", exc_info=True)
            return None
        if (
            probe_result.status == "unsupported"
            or probe_result.probability_coverage < settings.minimum_probability_coverage
        ):
            if settings.fail_closed_in_research:
                raise LLMVerifierCapabilityError(
                    "verifier-on run requires native logprobs with adequate "
                    f"coverage; probe failed: {probe_result.error}"
                )
            logger.warning(
                "Verifier endpoint unsupported (%s); disabling observer",
                probe_result.error or probe_result.status,
            )
            return None

        score_tokens = _DEFAULT_SCORE_TOKENS
        # token_budget_ratio 的运行时消费者：候选级 token 上限 =
        # 比例 × 本轮总 token 预算（§11 预算进入运行期）。
        max_tokens_per_candidate = None
        if getattr(e._config, "token_budget", 0):  # noqa: SLF001
            max_tokens_per_candidate = int(
                settings.token_budget_ratio * e._config.token_budget  # noqa: SLF001
            )
        service = VerificationService(
            e._db,  # noqa: SLF001
            e._artifact_store,  # noqa: SLF001
            model=settings.model,
            prompt_version_id="verifier-observer-v1",
            granularity=settings.granularity,
            repetitions=settings.repetitions,
            criteria=tuple(settings.criteria),
            order_seed=e._config.seed,  # noqa: SLF001
            capability_hash=probe_result.capability_hash,
            mode="observer",
            fail_closed=settings.fail_closed_in_research,
            score_tokens=score_tokens,
            temperature=settings.temperature,
        )
        config = ProbabilisticVerifierConfig(
            model=settings.model,
            criteria=tuple(settings.criteria),
            granularity=settings.granularity,
            repetitions=settings.repetitions,
            temperature=settings.temperature,
            minimum_probability_coverage=settings.minimum_probability_coverage,
            prompt_version_id="verifier-observer-v1",
            score_tokens=score_tokens,
            max_calls_per_candidate=settings.max_calls_per_candidate,
            max_tokens_per_candidate=max_tokens_per_candidate,
            # live 模式（未实现，PR4+）要求成对 A/B 交换；observer 证据
            # 模式由 order_seed 决定首个顺序，不强制 repetitions >= 2。
            enforce_paired_swap=settings.mode != "observer",
            live_min_repetitions=settings.live_min_repetitions,
        )
        verifier = ProbabilisticVerifier(
            e._llm,  # noqa: SLF001
            config,
            experiment_id=e._experiment_id,  # noqa: SLF001
        )
        observer = VerifierObserver(
            service,
            verifier,
            criteria=tuple(settings.criteria),
            granularity=settings.granularity,
            repetitions=settings.repetitions,
            order_seed=e._config.seed,  # noqa: SLF001
        )
        e._verifier_observer = observer  # noqa: SLF001
        return observer

    def _observe_verifier(self, prepared: PreparedCandidate) -> None:
        """PR2: observer-only verifier hook（集成计划 §9.1）.

        条件：verifier 启用、候选通过硬正确性测试、存在 parent。
        observer 只写证据；任何失败只记录，不阻断进化。
        """
        observer = self._ensure_verifier_observer()
        if observer is None:
            return
        if prepared.output is None or not prepared.output.passed or not prepared.parent_ids:
            return
        e = self._e
        try:
            code_text = e._artifact_store.load_text(prepared.artifact_hash) or ""  # noqa: SLF001
            result = prepared.sandbox_result
            metrics = prepared.output.metrics or {}
            execution_summary = {
                "execution_time_ms": getattr(result, "execution_time_ms", None),
                "memory_peak_kb": getattr(result, "memory_peak_kb", None),
                "cpu_time_ms": getattr(result, "cpu_time_ms", None),
                "early_stopped": metrics.get("evaluation_early_stopped", False),
            }
            observer.observe(
                candidate_id=prepared.candidate_id,
                peer_id=prepared.parent_ids[0],
                code_text=code_text,
                output=prepared.output,
                execution_summary=execution_summary,
                thought_summary=prepared.thought_summary,
                mechanism_tags=prepared.mechanism_tags,
                generation=prepared.generation,
                island_id=prepared.island_id,
                task_name=getattr(e, "_task_name", ""),  # noqa: SLF001
                experiment_id=e._experiment_id,  # noqa: SLF001
                evaluator_version_id=e._evaluator_version_id,  # noqa: SLF001
                environment_version_id=e._environment_version_id,  # noqa: SLF001
                db=e._db,  # noqa: SLF001
                artifact_store=e._artifact_store,  # noqa: SLF001
            )
        except Exception:
            logger.debug("Verifier observer skipped: %s", __import__("traceback").format_exc())

    def evaluate_candidate(
        self,
        candidate_id: str,
        artifact_hash: str,
        manifest_hash: str | None = None,
    ) -> EvalOutput | None:
        """评估候选（步骤 9-11）+ 记录 evaluation_run.

        Phase 3: 支持渐进式评估（Stage 0→3，任一阶段失败则 early-exit）。
        """
        # EvaluationService owns fidelity dispatch for every caller.
        return self._evaluate_full(candidate_id, artifact_hash, manifest_hash)

    def _evaluate_progressive(
        self,
        candidate_id: str,
        artifact_hash: str,
        manifest_hash: str | None = None,
    ) -> EvalOutput | None:
        """Compatibility wrapper; EvaluationService now owns progressive fidelity."""
        return self._evaluate_full(candidate_id, artifact_hash, manifest_hash)

    def _evaluate_full(
        self,
        candidate_id: str,
        artifact_hash: str,
        manifest_hash: str | None = None,
    ) -> EvalOutput | None:
        """全量评估 — _execute_sandbox + _apply_eval_result."""
        output, eval_run, job, result = self._execute_sandbox(
            candidate_id, artifact_hash, manifest_hash
        )
        if output is None:
            return None
        self._apply_eval_result(
            candidate_id,
            artifact_hash,
            output,
            eval_run.id if eval_run else None,
            job,
            result,
        )
        return output

    def _execute_sandbox(
        self,
        candidate_id: str,
        artifact_hash: str,
        manifest_hash: str | None = None,
        *,
        extra_metrics: dict[str, object] | None = None,
    ) -> tuple[EvalOutput | None, Any, Any, Any]:
        """Phase 3: 步骤 9-10 — sandbox 执行 + 结果解析（无状态变更）.

        返回 (output, eval_run, job, sandbox_result)。
        """
        e = self._e

        candidate_artifact = CandidateArtifact(
            candidate_id=candidate_id,
            source_hash=artifact_hash,
            manifest_hash=manifest_hash,
            language="python",
        )
        eval_context = EvaluationContext(
            experiment_id=e._experiment_id,  # noqa: SLF001
            evaluator_version_id=e._evaluator_version_id,  # noqa: SLF001
            environment_version_id=e._environment_version_id,  # noqa: SLF001
            seed=e._config.seed,  # noqa: SLF001
        )

        # 创建评估运行记录
        try:
            run = e._eval_repo.create(  # noqa: SLF001
                experiment_id=e._experiment_id,  # noqa: SLF001
                candidate_id=candidate_id,
                evaluator_version_id=e._evaluator_version_id,  # noqa: SLF001
                environment_version_id=e._environment_version_id,  # noqa: SLF001
                seed=e._config.seed,  # noqa: SLF001
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
            # Fix 2: 立即 claim 使 job 进入 running 状态，否则 complete/fail 永远失败
            if job:
                claimed = e._job_store.claim_job_by_id(job.id)  # noqa: SLF001
                if claimed:
                    job = claimed
        except Exception:
            logger.debug("Could not create job record", exc_info=True)

        # Unified evaluation entry: validation → anti-cheat → progressive
        # stages → hidden plans → repeated benchmark → robust aggregation.
        from omnievolve.eval.evaluation_service import EvaluationService

        policy = SandboxPolicy(
            timeout_sec=e._config.sandbox_timeout,  # noqa: SLF001
            mem_limit_mb=e._config.sandbox_mem_limit_mb,  # noqa: SLF001
        )
        service = EvaluationService(
            e._task_evaluator,  # noqa: SLF001
            e._sandbox,  # noqa: SLF001
            e._artifact_store,  # noqa: SLF001
            progressive=e._config.progressive_eval_enabled,  # noqa: SLF001
            repetitions=e._config.eval_repetitions,  # noqa: SLF001
            confidence=e._config.eval_confidence,  # noqa: SLF001
        )
        try:
            outcome = service.evaluate(
                candidate_artifact,
                eval_context,
                policy,
                extra_metrics=extra_metrics,
            )
        except EvaluatorError:
            logger.exception("Failed to build/parse evaluation for %s", candidate_id)
            if run:
                e._eval_repo.fail(run.id, "evaluation plan error")  # noqa: SLF001
            return None, run, job, None
        except SandboxError:
            logger.exception("Sandbox execution failed for %s", candidate_id)
            if run:
                e._eval_repo.fail(run.id, "sandbox execution error")  # noqa: SLF001
            if job:
                try:
                    e._job_store.fail_job(job.id, "sandbox execution error")  # noqa: SLF001
                except Exception:
                    logger.warning("Job fail_job failed for %s", job.id, exc_info=True)
            return None, run, job, None

        output = outcome.output
        result = outcome

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
                # Keep the evaluator's primary task score immutable.  The
                # auxiliary objective is consumed by LineageUCB only.
                blended = min(output.score + beta * epi_score, 1.0)
                output = EvalOutput(
                    score=output.score,
                    metrics={
                        **output.metrics,
                        "epiplexity": epi_score,
                        "task_score": output.score,
                        "search_score": blended,
                    },
                    passed=output.passed,
                    failure_reason=output.failure_reason,
                    confidence=output.confidence,
                )
            except Exception:
                logger.debug("Epiplexity scoring failed for %s", artifact_hash, exc_info=True)

        # 完成评估运行记录（含 stdout/stderr 存储用于 debug）
        if run:
            try:
                stdout_hash = None
                stderr_hash = None
                if getattr(result, "stdout", None):
                    stdout_hash = e._artifact_store.store_text(result.stdout[:5000], "log")  # noqa: SLF001
                if getattr(result, "stderr", None):
                    stderr_hash = e._artifact_store.store_text(result.stderr[:5000], "log")  # noqa: SLF001
                e._eval_repo.complete(  # noqa: SLF001
                    run.id,
                    passed=output.passed,
                    primary_score=output.score,
                    metrics=output.metrics,
                    execution_time_ms=result.execution_time_ms,
                    memory_peak_kb=result.memory_peak_kb,
                    cpu_time_ms=result.cpu_time_ms,
                    stdout_hash=stdout_hash,
                    stderr_hash=stderr_hash,
                )
            except StorageError:
                logger.debug("Could not complete evaluation_run record", exc_info=True)

        return output, run, job, outcome

    def _apply_eval_result(
        self,
        candidate_id: str,
        artifact_hash: str,
        output: EvalOutput,
        eval_run_id: str | None = None,
        job: Any = None,
        result: Any = None,
        reference_ids: list[str] | None = None,
        parent_ids: list[str] | None = None,
        candidate_novelty: NoveltyResult | None = None,
        *,
        search_credit_enabled: bool = True,
    ) -> None:
        """Phase 3: 步骤 11 — 所有共享状态变更（串行执行）.

        从 _execute_sandbox 拆分出的状态更新逻辑。
        """
        e = self._e

        # 设计文档 §6: Plugin.enrich_evaluation — 补充领域指标
        output = self._enrich_with_plugins(candidate_id, artifact_hash, output)

        # 更新 candidate 状态
        e._candidate_repo.update_status(candidate_id, "evaluated" if output.passed else "failed")  # noqa: SLF001

        # Phase 4: 数据泄漏检测（高分候选自动触发）
        if (
            output.passed
            and output.score > e._config.leakage_score_threshold
            and getattr(e, "_leakage_detector", None)
        ):  # noqa: SLF001
            try:
                code_text = e._artifact_store.load_text(artifact_hash)  # noqa: SLF001
                baseline = e._get_baseline_score()  # noqa: SLF001
                leak_result = e._leakage_detector.check(  # type: ignore[attr-defined]  # noqa: SLF001
                    code_text or "", "", output.score, baseline
                )
                if leak_result.has_leakage and leak_result.confidence == "high":
                    logger.warning("Data leakage detected: %s", leak_result.reason)
                    output = type(output)(
                        score=output.score * e._config.leakage_penalty_factor,
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
        if len(e._recent_scores) > 200:  # noqa: SLF001
            e._recent_scores = e._recent_scores[-100:]  # noqa: SLF001

        # meta-scratchpad
        thought_text = ""
        cand_meta = e._candidate_repo.get_candidate(candidate_id)  # noqa: SLF001
        if cand_meta and cand_meta.meta:
            thought_text = cand_meta.meta.get("thought", "")
        e._update_meta_scratchpad(thought_text, output.score)  # noqa: SLF001

        # LineageUCB/reference 回传（relative child-vs-parent gain).
        if search_credit_enabled:
            parent_scores = [
                e._get_candidate_score(parent_id)  # noqa: SLF001
                for parent_id in (parent_ids or [])
            ]
            parent_best = max(parent_scores) if parent_scores else e._get_baseline_score()  # noqa: SLF001
            search_score = float(output.metrics.get("search_score", output.score))
            relative_gain = search_score - parent_best
            normalized_gain = 0.5 + 0.5 * max(-1.0, min(1.0, relative_gain))
            e._mcts.backpropagate(candidate_id, normalized_gain)  # noqa: SLF001
            if e._config.reference_credit_enabled and reference_ids:  # noqa: SLF001
                e._mcts.credit_references(  # noqa: SLF001
                    reference_ids,
                    normalized_gain,
                    weight=e._config.reference_credit_weight,  # noqa: SLF001
                    exclude_ids={candidate_id},
                )

        # 岛屿精英更新
        island_id = e._lookup_island(candidate_id)  # noqa: SLF001
        if island_id:
            island = e._island_manager.get_island(island_id)  # noqa: SLF001
            if island:
                island.update_elite(candidate_id, output.score)
                if candidate_novelty is not None:
                    island.update_novelty(
                        candidate_id,
                        candidate_novelty.objective_score,
                    )
                generation = (
                    cand_meta.generation if cand_meta is not None else e._current_generation
                )  # noqa: SLF001
                island.record_generation_score(
                    generation,
                    output.score,
                    passed=output.passed,
                )
                if output.passed and e._behavior_archive is not None:  # noqa: SLF001
                    try:
                        code_text = e._artifact_store.load_text(artifact_hash) or ""  # noqa: SLF001
                        changed = e._behavior_archive.update(  # noqa: SLF001
                            island_id=island_id,
                            candidate_id=candidate_id,
                            score=output.score,
                            code=code_text,
                            metrics=output.metrics,
                        )
                        logger.info(
                            "behavior_archive_update candidate=%s island=%s changed=%s",
                            candidate_id,
                            island_id,
                            changed,
                        )
                    except Exception:
                        logger.warning(
                            "Behavior archive update failed for %s",
                            candidate_id,
                            exc_info=True,
                        )

        # 搜索状态更新
        e._candidate_repo.update_search_state(  # noqa: SLF001
            candidate_id,
            visit_delta=1,
            value_delta=(normalized_gain if search_credit_enabled else output.score),
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
        if result is not None:
            e._budget_guard.consume(  # noqa: SLF001
                model="sandbox",
                input_tokens=0,
                output_tokens=0,
                compute_sec=result.execution_time_ms / 1000,
                cost_usd=0.0,
                cost_known=True,
            )

        # Phase 4.4: 完成 Job 记录
        if job:
            try:
                job_id = job if isinstance(job, str) else job.id
                e._job_store.complete_job(job_id, result_ref=artifact_hash)  # noqa: SLF001
            except Exception:
                logger.warning("Job complete_job failed for %s", job_id, exc_info=True)

    def _enrich_with_plugins(
        self,
        candidate_id: str,
        artifact_hash: str,
        output: EvalOutput,
    ) -> EvalOutput:
        """设计文档 §6: 调用已注册插件的 enrich_evaluation 补充领域指标.

        注意：只能补充领域指标或发出约束告警，不能静默改写任务主分数。
        """
        try:
            from omnievolve.plugins.discovery import _REGISTERED_PLUGINS

            if not _REGISTERED_PLUGINS:
                return output

            candidate = CandidateArtifact(
                candidate_id=candidate_id,
                source_hash=artifact_hash,
                manifest_hash=None,
                language="python",
            )

            enriched_metrics: dict = {}
            for name, plugin in _REGISTERED_PLUGINS.items():
                try:
                    result = plugin.enrich_evaluation(candidate, output)
                    if result:
                        enriched_metrics[name] = result
                except Exception:
                    logger.debug("Plugin %s enrich_evaluation failed", name, exc_info=True)

            if enriched_metrics:
                # 合并插件指标到 output.metrics，不改写 score/passed
                output = type(output)(
                    score=output.score,
                    metrics={**output.metrics, "plugin_enrichment": enriched_metrics},  # type: ignore[dict-item]
                    passed=output.passed,
                    failure_reason=output.failure_reason,
                    confidence=output.confidence,
                )
        except Exception:
            logger.debug("Plugin enrichment skipped", exc_info=True)

        return output

    def _update_router_reward(
        self,
        role_models: dict[str, str],
        role_calls: set[str],
        output: EvalOutput,
        parent_ids: list[str],
        thought_adopted: bool = True,
        mechanism_novelty: float = 0.5,
        critic_passed: bool = True,
    ) -> None:
        """Router 奖励更新 — 设计文档 §5.5 角色奖励分离.

        Director: thought_adoption + mechanism_novelty + frontier_contribution
        Coder: patch_apply + compile + test_pass + performance_gain (Shinka)
        Critic: defect_recall + false_rejection + cost_saved
        """
        from omnievolve.agents.router import (
            compute_critic_reward,
            compute_director_reward,
            compute_shinka_reward,
        )

        e = self._e
        assert e._router is not None  # noqa: SLF001

        # 查父代分数
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

        # Coder reward is assigned only to the model that actually produced code.
        if "coder" in role_calls and role_models.get("coder"):
            coder_reward = compute_shinka_reward(output.score, parent_score, baseline_score)
            e._router.update(  # noqa: SLF001
                model=role_models["coder"],
                role="coder",
                reward=coder_reward,
            )

        # Director 奖励: thought 被采纳 + 机制新颖性 + 前沿贡献
        frontier_contribution = max(output.score - baseline_score, 0.0)
        director_reward = compute_director_reward(
            thought_adopted=thought_adopted,
            mechanism_novelty=mechanism_novelty,
            frontier_contribution=frontier_contribution,
        )
        if "director" in role_calls and role_models.get("director"):
            e._router.update(  # noqa: SLF001
                model=role_models["director"],
                role="director",
                reward=director_reward,
            )

        # Critic 奖励: 缺陷召回 + 低误拒 + 节省评估成本
        # 交叉引用 output.passed 和 critic_passed:
        # - defect_recall 高: Critic 正确拒绝了坏候选 (not passed & not critic_passed)
        # - false_rejection 高: Critic 错误拒绝了好候选 (passed & not critic_passed)
        # - cost_saved 高: Critic 正确拦截坏候选，节省 sandbox 成本
        defect_recall = 0.5 if (not output.passed and not critic_passed) else 0.0
        false_rejection = 0.3 if (output.passed and not critic_passed) else 0.0
        cost_saved = 0.3 if (not output.passed and not critic_passed) else 0.0
        if "critic" in role_calls and role_models.get("critic"):
            critic_reward = compute_critic_reward(
                defect_recall=defect_recall,
                false_rejection_rate=false_rejection,
                evaluator_cost_saved=cost_saved,
            )
            e._router.update(  # noqa: SLF001
                model=role_models["critic"],
                role="critic",
                reward=critic_reward,
            )

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
