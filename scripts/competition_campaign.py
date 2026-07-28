"""Run OmniEvolve in auditable 10-generation competition checkpoints.

The controller never blindly launches all remaining generations.  After every checkpoint
it writes a Markdown report, applies challenge-specific health gates, and stops on a
pipeline regression so the evaluator or candidate can be repaired before resuming.
"""

from __future__ import annotations

import argparse
import atexit
import json
import math
import os
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
OMNIEVOLVE = ROOT / ".venv" / "Scripts" / "omnievolve.exe"


def _rows(db_path: Path, experiment_id: str) -> list[dict]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT c.id candidate_id, c.generation, c.status candidate_status,
                   e.status eval_status, e.passed, e.primary_score, e.metrics,
                   e.execution_time_ms, e.finished_at
            FROM candidate c
            LEFT JOIN evaluation_run e ON e.candidate_id=c.id
            WHERE c.experiment_id=?
            ORDER BY c.generation, c.created_at
            """,
            (experiment_id,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["metrics"] = json.loads(item["metrics"] or "{}")
        except json.JSONDecodeError:
            item["metrics"] = {}
        result.append(item)
    return result


def _experiment(db_path: Path, experiment_id: str) -> dict:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM experiment WHERE id=?", (experiment_id,)
        ).fetchone()
    if row is None:
        raise RuntimeError(f"experiment not found: {experiment_id}")
    return dict(row)


def _checkpoint_generation(experiment: dict) -> int:
    """Return the generation that resume() will actually restore.

    Candidate rows can be written before the end-of-generation checkpoint.  If
    a process is interrupted in that window, MAX(candidate.generation) is ahead
    of resume state and must not be used to choose the next ``--gens`` target.
    """
    try:
        checkpoint = json.loads(experiment.get("checkpoint_data") or "{}")
        generation = int(checkpoint.get("generation", 0))
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        return 0
    return max(0, generation)


def _cumulative_usage(db_path: Path, experiment_id: str) -> tuple[int, float]:
    """Read cumulative usage from append-only ledgers, not overwritten summaries."""
    with sqlite3.connect(db_path) as conn:
        token_row = conn.execute(
            "SELECT COALESCE(SUM(total_tokens), 0) FROM llm_call_ledger "
            "WHERE experiment_id=?",
            (experiment_id,),
        ).fetchone()
        compute_row = conn.execute(
            "SELECT COALESCE(SUM(execution_time_ms), 0) FROM evaluation_run "
            "WHERE experiment_id=? AND status='completed'",
            (experiment_id,),
        ).fetchone()
    return int(token_row[0] or 0), float(compute_row[0] or 0.0) / 1000.0


def _generation_summary(rows: list[dict], generation: int) -> list[str]:
    lines = [
        "| 代 | 候选数 | passed | 最好分数 | 中位分数 |",
        "|---:|---:|---:|---:|---:|",
    ]
    for gen in range(max(0, generation - 9), generation + 1):
        current = [r for r in rows if r["generation"] == gen and r["primary_score"] is not None]
        scores = [float(r["primary_score"]) for r in current]
        lines.append(
            f"| {gen} | {len(current)} | {sum(bool(r['passed']) for r in current)} "
            f"| {max(scores):.12g} | {median(scores):.12g} |"
            if scores
            else f"| {gen} | 0 | 0 | — | — |"
        )
    return lines


def _health(challenge: str, rows: list[dict], generation: int) -> tuple[bool, list[str]]:
    first_generation = max(1, generation - 9)
    recent = [
        r
        for r in rows
        if first_generation <= r["generation"] <= generation
    ]
    reasons: list[str] = []
    expected_generations = set(range(first_generation, generation + 1))
    completed_generations = {
        int(r["generation"]) for r in recent if r["eval_status"] == "completed"
    }
    missing_generations = sorted(expected_generations - completed_generations)
    if missing_generations:
        reasons.append(f"缺少完成评估的 generation：{missing_generations}")
    incomplete = [r for r in recent if r["eval_status"] != "completed"]
    if incomplete:
        reasons.append(f"存在 {len(incomplete)} 个未完成 evaluation")
    completed = [r for r in recent if r["eval_status"] == "completed"]
    finite_scores = [
        r
        for r in completed
        if r["primary_score"] is not None and math.isfinite(float(r["primary_score"]))
    ]
    if len(finite_scores) != len(completed):
        reasons.append("存在缺失或非有限 primary score")

    # A failed candidate is a normal, useful outcome of evolutionary search:
    # it proves the evaluator rejected an incorrect mutation.  Pipeline health
    # is about durable generation coverage and completed, finite evaluations,
    # not the fraction of proposals that happened to be correct.
    passed = [r for r in rows if r["passed"] and r["primary_score"] is not None]
    if not passed:
        reasons.append("实验没有任何 passed 候选")
    else:
        best = max(passed, key=lambda row: float(row["primary_score"]))
        metrics = best["metrics"]
        if challenge == "occam":
            if metrics.get("min_train_acc") != 1.0 or metrics.get("min_test_acc") != 1.0:
                reasons.append("Occam best 未保持四题 train/holdout 全精确")
        elif challenge == "lj924":
            if float(metrics.get("max_atom_force", float("inf"))) >= 1e-8:
                reasons.append("LJ924 best 未通过严格力门")
            if not metrics.get("monotonicity_ok", False):
                reasons.append("LJ924 best 未通过平均对能单调必要条件")
    return not reasons, reasons


def write_report(
    challenge: str,
    db_path: Path,
    experiment_id: str,
    generation: int,
    output: Path,
) -> bool:
    rows = _rows(db_path, experiment_id)
    passed = [r for r in rows if r["passed"] and r["primary_score"] is not None]
    best = max(passed, key=lambda row: float(row["primary_score"])) if passed else None
    baseline = next((r for r in rows if r["generation"] == 0), None)
    healthy, reasons = _health(challenge, rows, generation)
    recent = [r for r in rows if max(1, generation - 9) <= r["generation"] <= generation]
    pass_rate = sum(bool(r["passed"]) for r in recent) / max(1, len(recent))
    cumulative_tokens, cumulative_compute = _cumulative_usage(db_path, experiment_id)

    text = [
        f"# {challenge} OmniEvolve 第 {max(1, generation - 9)}–{generation} 轮总结",
        "",
        f"- 实验 ID：`{experiment_id}`",
        f"- pipeline：**{'健康，可继续' if healthy else '异常，已停止待修'}**",
        f"- 本批候选：{len(recent)}；候选 correctness 通过率：{pass_rate:.1%}"
        "（仅作搜索统计，不作为 pipeline 健康门）",
        f"- 累计 tokens：{cumulative_tokens}；累计 evaluator compute："
        f"{cumulative_compute:.1f}s",
    ]
    if best:
        text.extend(
            [
                f"- 当前 best：`{best['candidate_id']}`（generation {best['generation']}，"
                f"score={float(best['primary_score']):.12g}）",
                "",
                "## 当前 best 指标",
                "",
                "```json",
                json.dumps(best["metrics"], ensure_ascii=False, indent=2, sort_keys=True),
                "```",
            ]
        )
    if baseline and best:
        text.extend(
            [
                "",
                "## 相对基线",
                "",
                f"- 基线 score：{float(baseline['primary_score']):.12g}",
                f"- best score：{float(best['primary_score']):.12g}",
                f"- Δscore：{float(best['primary_score']) - float(baseline['primary_score']):+.12g}",
            ]
        )
        if challenge == "occam":
            b_gates = int(baseline["metrics"].get("total_gates", 0))
            g_gates = int(best["metrics"].get("total_gates", 0))
            text.append(f"- 总门数：{b_gates} → {g_gates}（Δ={g_gates - b_gates:+d}）")
        elif challenge == "lj924":
            text.append(
                f"- 相对严格 incumbent 的 ΔE："
                f"{float(best['metrics'].get('delta_vs_strict_baseline', 0.0)):+.12g}"
            )
            text.append(
                f"- 搜索性质：`{best['metrics'].get('search_mode', 'unknown')}`；"
                f"unbiased={best['metrics'].get('unbiased', False)}"
            )

    text.extend(["", "## 逐代状态", "", *_generation_summary(rows, generation)])
    text.extend(["", "## 本批策略与结果分类", ""])
    if challenge == "lj924":
        best_modes = Counter(
            str(r["metrics"].get("search_mode", "missing-result"))
            for r in recent
        )
        attempted_modes = Counter(
            mode
            for r in recent
            for mode in r["metrics"].get("attempted_modes", [])
        )
        text.append("- 最终最好 basin：")
        for mode, count in best_modes.most_common():
            text.append(f"  - `{mode}`：{count} 轮")
        text.append("- 实际筛选过的结构种子：")
        if attempted_modes:
            for mode, count in attempted_modes.most_common():
                text.append(f"  - `{mode}`：{count} 次")
        else:
            text.append("  - 历史候选未记录 `attempted_modes`")
        real_improvements = sum(
            bool(r["passed"])
            and float(r["metrics"].get("delta_vs_strict_baseline", 0.0)) > 1e-8
            for r in recent
        )
        text.append(f"- 严格可验证的真实能量改善：{real_improvements} 轮")
        text.append(f"- verifier 拒绝：{sum(not bool(r['passed']) for r in recent)} 轮")
    else:
        exact = [
            r
            for r in recent
            if r["metrics"].get("min_train_acc") == 1.0
            and r["metrics"].get("min_test_acc") == 1.0
        ]
        gate_counts = Counter(
            int(r["metrics"]["total_gates"])
            for r in exact
            if r["metrics"].get("total_gates") is not None
        )
        text.append(f"- 四题 train/holdout 全精确：{len(exact)} 轮")
        text.append(
            "- 精确候选门数分布："
            + (
                "，".join(f"{gates} gates×{count}" for gates, count in sorted(gate_counts.items()))
                if gate_counts
                else "无"
            )
        )
        text.append(f"- exactness 失败：{len(recent) - len(exact)} 轮")
    text.extend(["", "## 理解与下一步", ""])
    if challenge == "occam":
        text.append(
            "- 精度优先于门数；只有四个 mystery 都保持精确时，门共享、乘法列压缩、"
            "carry-save/Wallace/Dadda 等结构改写才算真实进展。"
        )
    else:
        text.append(
            "- LJ924 是单一 2004 lattice-seeded 来源附近的高局部插值残差点；"
            "incumbent 重最小化只构成 audit/match，只有独立形态搜索得到 ΔE>0 才是 catch。"
        )
    if reasons:
        text.extend(["", "## 停机原因", "", *[f"- {reason}" for reason in reasons]])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(text) + "\n", encoding="utf-8")
    return healthy


def wait_until_idle(db_path: Path, experiment_id: str, poll_seconds: int) -> int:
    while True:
        exp = _experiment(db_path, experiment_id)
        # This must match EvolutionEngine.resume(), which restores checkpoint_data.
        # A completed evaluation written just before an interruption is useful audit
        # evidence, but it is not a committed generation until checkpoint save.
        generation = _checkpoint_generation(exp)
        if exp["status"] != "running":
            return generation
        print(
            f"[campaign] waiting: experiment={experiment_id} generation={generation}",
            flush=True,
        )
        time.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--challenge", choices=("occam", "lj924"), required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--evaluator", required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--first-checkpoint", type=int, default=10)
    parser.add_argument("--final-generation", type=int, default=110)
    parser.add_argument("--checkpoint-size", type=int, default=10)
    parser.add_argument(
        "--max-subprocesses",
        type=int,
        default=1,
        help=(
            "Maximum individual generation invocations this controller process may run. "
            "The default keeps desktop-tool calls bounded; invoke the controller again "
            "to continue from the database checkpoint."
        ),
    )
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20260728)
    args = parser.parse_args()

    config = (ROOT / args.config).resolve()
    import tomllib

    with config.open("rb") as handle:
        cfg = tomllib.load(handle)
    db_path = (ROOT / cfg["storage"]["db_path"]).resolve()
    # Experiments are deliberately immutable audit units.  Do not append a
    # restarted campaign's reports or subprocess logs to a prior failed run.
    reports = ROOT / ".omnievolve" / "reports" / args.challenge / args.experiment_id
    lock_path = ROOT / ".omnievolve" / f"campaign-{args.experiment_id}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = lock_path.open("x", encoding="utf-8")
    except FileExistsError:
        print(
            f"[campaign] exclusive lock already exists: {lock_path}; "
            "refusing a concurrent resume",
            flush=True,
        )
        return 4
    descriptor.write(str(os.getpid()))
    descriptor.close()

    def release_lock() -> None:
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass

    atexit.register(release_lock)

    completed = wait_until_idle(db_path, args.experiment_id, args.poll_seconds)
    checkpoint = max(args.first_checkpoint, completed)
    if checkpoint % args.checkpoint_size:
        checkpoint = ((checkpoint // args.checkpoint_size) + 1) * args.checkpoint_size

    invocations = 0
    while checkpoint <= args.final_generation:
        # Reach the requested boundary before producing its report.  A previous
        # version used ``if`` here, so a multi-generation controller wrote (for
        # example) a generation-010 report immediately after generation 6 and
        # then applied the generation-020 health gate after generation 7.
        while completed < checkpoint:
            # The invocation budget applies to the entire controller run, not
            # independently inside each checkpoint.  Check before launching so
            # reaching generation 10 with a budget of five cannot spill into 11.
            if invocations >= args.max_subprocesses:
                print(
                    "[campaign] bounded handoff: re-invoke this controller to continue; "
                    f"next generation={completed + 1}",
                    flush=True,
                )
                return 0
            # A single model call can take minutes.  Keep each invocation to one
            # new generation so an external UI timeout cannot erase progress from
            # a whole ten-generation checkpoint.  The SQLite checkpoint is the
            # source of truth after every subprocess, never our requested target.
            target_generation = completed + 1
            log_dir = ROOT / ".omnievolve" / "runs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / (
                f"{args.challenge}_{args.experiment_id}_g{target_generation:03d}_{target_generation:03d}.campaign.log"
            )
            command = [
                str(OMNIEVOLVE),
                "run",
                "--resume",
                args.experiment_id,
                "-e",
                args.evaluator,
                "-c",
                str(config),
                "--gens",
                str(target_generation),
                "--trusted",
                "--no-self-evolve",
                "--seed",
                str(args.seed),
            ]
            with log_path.open("a", encoding="utf-8") as log:
                run = subprocess.run(
                    command,
                    cwd=ROOT,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            if run.returncode != 0:
                print(f"[campaign] OmniEvolve failed; see {log_path}", flush=True)
                return 2
            observed = wait_until_idle(db_path, args.experiment_id, args.poll_seconds)
            if observed <= completed:
                print(
                    "[campaign] OmniEvolve returned without a durable generation; "
                    f"requested={target_generation}, observed={observed}; see {log_path}",
                    flush=True,
                )
                return 2
            completed = observed
            invocations += 1
            print(
                f"[campaign] durable generation={completed}; "
                f"invocations_this_run={invocations}",
                flush=True,
            )
        report = reports / f"generation-{checkpoint:03d}.md"
        healthy = write_report(
            args.challenge, db_path, args.experiment_id, checkpoint, report
        )
        print(f"[campaign] wrote {report}; healthy={healthy}", flush=True)
        if not healthy:
            return 3
        checkpoint += args.checkpoint_size
    return 0


if __name__ == "__main__":
    sys.exit(main())
