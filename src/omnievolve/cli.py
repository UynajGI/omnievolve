"""OmniEvolve CLI.

完整命令集：
    run     — 启动候选进化（Fast + Slow Loop）
    resume  — 断点续跑（通过 run --resume）
    status  — 查看进化进度、Champion Policy、健康状态
    best    — 输出最优 Candidate Artifact
    export  — 导出进化图（GraphML / JSON）
    policy  — 查看 Champion / Challenger 策略谱系
    audit   — 检查 Artifact 哈希、评估器版本、缺失向量索引
    recover — 扫描租约过期任务、未完成 Outbox、孤立 Artifact
    doctor  — 环境检测
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from omnievolve.config import (
    OmniEvolveSettings,
    build_evolution_config,
    build_model_slots,
    load_evaluator,
    load_settings,
)

app = typer.Typer(
    name="omnievolve",
    help="OmniEvolve - 受控元进化框架",
    add_completion=False,
)
console = Console()


# --------------------------------------------------------------------------- #
#  Bootstrap helpers
# --------------------------------------------------------------------------- #


def _bootstrap(
    config_path: str | None,
    *,
    trusted: bool = False,
) -> tuple:
    """加载配置、初始化 DB/migrations、artifact_store、sandbox.

    Returns:
        (settings, db, artifact_store, sandbox)
    """
    settings = load_settings(config_path)

    from omnievolve.storage.db import Database
    from omnievolve.storage.migrations import initialize_database

    storage = settings.storage
    Path(storage.db_path).parent.mkdir(parents=True, exist_ok=True)
    Path(storage.artifact_dir).mkdir(parents=True, exist_ok=True)

    db = Database(storage.db_path)
    initialize_database(db)

    # 代码存储后端：根据 config.code_backend 选择 CAS 或 Git
    from omnievolve.storage.code_store import create_code_store

    artifact_store = create_code_store(storage, db)

    from omnievolve.sandbox.registry import create_backend

    backend_type = "trusted_subprocess" if trusted else settings.sandbox.backend
    sandbox = create_backend(
        backend_type,
        trusted=trusted,
        work_dir=str(Path(storage.db_path).parent / "sandbox"),
        artifact_store=artifact_store,
    )

    return settings, db, artifact_store, sandbox


def _build_engine_components(
    db,
    settings: OmniEvolveSettings,
    sandbox,
    llm,  # noqa: ANN001
) -> dict:
    """构造 EvolutionEngine 所需的全部组件（router/island/self_evaluator/meta...）."""
    from omnievolve.agents.router import ModelRouter
    from omnievolve.engine.crossover import CrossoverOperator
    from omnievolve.engine.island import IslandManager
    from omnievolve.engine.selection import ParentSelector
    from omnievolve.eval.telemetry import HealthPolicy, SelfEvaluator, TelemetryAggregator
    from omnievolve.meta.governance import (
        GovernancePolicy,
        L0PolicyMutator,
        MetaPlanner,
        ReplayEvaluator,
    )
    from omnievolve.meta.hyperparam_tuner import BayesianTuner
    from omnievolve.meta.policy_archive import PolicyArchive
    from omnievolve.storage.graph_store import GraphStore

    model_slots = build_model_slots(settings)
    router = (
        ModelRouter(model_slots, algorithm=settings.models.routing.algorithm)
        if model_slots
        else None
    )
    island_manager = IslandManager(
        num_islands=settings.evolution.island_count,
        migration_interval=settings.selection.island_migration_interval,
    )
    parent_selector = ParentSelector(
        db,
        strategy="tournament",
        tournament_size=settings.selection.tournament_size,
    )
    crossover = CrossoverOperator()

    aggregator = TelemetryAggregator(db)
    health_policy = HealthPolicy(
        roi_warn_threshold=settings.self_evaluator.roi_warn_threshold,
        entropy_warn_threshold=settings.self_evaluator.entropy_warn_threshold,
        stagnation_trigger=settings.self_evaluator.stagnation_trigger,
    )
    self_evaluator = SelfEvaluator(aggregator, health_policy)

    governance = GovernancePolicy(
        auto_apply_l0=settings.meta_evolution.auto_apply_l0,
        require_replay_for_l1=settings.meta_evolution.require_replay_for_l1,
        allow_l2_actions=settings.meta_evolution.allow_l2_actions,
    )
    l0_mutator = L0PolicyMutator(governance)
    tuner = BayesianTuner() if settings.meta_evolution.enabled else None
    prompt_evolver = None
    if settings.meta_evolution.enabled:
        from omnievolve.meta.prompt_evolver import PromptEvolver

        prompt_evolver = PromptEvolver(mutation_rate=settings.meta_evolution.prompt_mutation_rate)
    meta_planner = MetaPlanner(l0_mutator, tuner=tuner, prompt_evolver=prompt_evolver)
    replay_evaluator = ReplayEvaluator(
        budget_ratio=settings.meta_evolution.meta_canary_budget_ratio,
        min_gain_threshold=settings.meta_evolution.promotion_min_gain,
        max_regression=settings.meta_evolution.promotion_max_regression,
    )

    meta_enabled = settings.meta_evolution.enabled

    # 向量索引器（设计文档 §4.2: Outbox → Embed → VectorBackend）
    vector_indexer = None
    try:
        from omnievolve.storage.vector_indexer import VectorIndexer
        from omnievolve.storage.zvec_backend import create_vector_backend
        from omnievolve.utils.embedding import FakeEmbedder

        # 尝试加载真实 embedding 模型，失败则用 FakeEmbedder
        embedder: Any = None
        try:
            from omnievolve.utils.embedding import SentenceTransformerEmbedder

            embedder = SentenceTransformerEmbedder(model=settings.embedding.code.model)
        except Exception:
            embedder = FakeEmbedder(dimension=128)

        # 优先 zvec（HNSW ANN），不可用时回退 NumPy
        vector_backend = create_vector_backend(prefer_zvec=True)
        vector_indexer = VectorIndexer(db, vector_backend, embedder)
    except Exception:
        pass  # core 模式无向量也可运行

    return {
        "router": router,
        "island_manager": island_manager,
        "parent_selector": parent_selector,
        "crossover": crossover,
        "policy_archive": PolicyArchive(db),
        "governance": governance,
        "self_evaluator": self_evaluator if meta_enabled else None,
        "meta_planner": meta_planner if meta_enabled else None,
        "replay_evaluator": replay_evaluator,
        "graph_store": GraphStore(db),
        "vector_indexer": vector_indexer,
    }


# --------------------------------------------------------------------------- #
#  Commands
# --------------------------------------------------------------------------- #


@app.command()
def run(
    task: str = typer.Argument(..., help="任务描述或初始代码文件路径"),
    config: str = typer.Option("omnievolve.toml", "--config", "-c", help="配置文件路径"),
    evaluator: str = typer.Option(..., "--evaluator", "-e", help="评估器路径 (module:Class)"),
    resume: str | None = typer.Option(None, "--resume", help="恢复实验 ID"),
    generations: int | None = typer.Option(None, "--gens", "-g", help="最大代数"),
    trusted: bool = typer.Option(False, "--trusted", help="启用非隔离 subprocess 模式"),
    no_self_evolve: bool = typer.Option(
        False, "--no-self-evolve", help="关闭 Slow Loop 受控策略进化，仅运行 Fast Loop"
    ),
) -> None:
    """启动候选进化；按健康窗口自动运行受控策略进化."""
    from omnievolve.utils.logging import setup_logging

    # 自动加载 .env / .local.env → os.environ（优先级: .local.env > .env > 环境变量）
    load_dotenv(".env", override=False)
    load_dotenv(".local.env", override=True)

    setup_logging()
    console.print("[bold green]OmniEvolve[/bold green] - Starting evolution")
    if trusted:
        console.print("[yellow]WARNING: trusted subprocess 模式（非隔离）[/yellow]")

    settings, db, artifact_store, sandbox = _bootstrap(config, trusted=trusted)
    eval_config = build_evolution_config(settings)
    if generations is not None:
        eval_config.max_generations = generations
    if no_self_evolve:
        eval_config.self_evolve_enabled = False
        console.print("[yellow]Self-evolve (Slow Loop) disabled — fast loop only[/yellow]")

    # 加载评估器
    evaluator_cls = load_evaluator(evaluator)
    task_evaluator = evaluator_cls()

    # 注册评估器版本
    from omnievolve.eval.evaluator_registry import EvaluatorRegistry

    registry = EvaluatorRegistry(db)
    evaluator_version_id = registry.register(task_evaluator)
    environment_version_id = sandbox.environment_version_id

    # LLM Gateway
    from omnievolve.agents.llm_gateway import LLMGateway

    llm = LLMGateway(
        db,
        default_model=(settings.models.light[0] if settings.models.light else "gpt-4o-mini"),
    )

    components = _build_engine_components(db, settings, sandbox, llm)

    # 读取初始代码
    task_path = Path(task)
    if task_path.exists():
        initial_code = task_path.read_text(encoding="utf-8")
        task_name = task_path.stem
    elif task_path.suffix in (".py", ".toml", ".txt"):
        # 看起来像文件路径但不存在 → 报错
        typer.echo(f"Error: 任务文件不存在: {task}", err=True)
        raise typer.Exit(code=1)
    else:
        initial_code = task
        task_name = task[:60]

    # 创建或恢复实验
    from omnievolve.storage.repositories.experiment_repo import ExperimentRepository

    exp_repo = ExperimentRepository(db)
    if resume:
        experiment_id = resume
    else:
        exp = exp_repo.create(
            task_id=task_name,
            task_name=task_name,
            config_snapshot={"evaluator": evaluator, "config": config},
        )
        experiment_id = exp.id

    # Git 后端: 绑定实验（按 task_name 创建 per-project 仓库）
    if hasattr(artifact_store, "bind_experiment"):
        artifact_store.bind_experiment(experiment_id, task_name=task_name)

    # 构造引擎
    from omnievolve.engine.evolution_engine import EvolutionEngine

    engine = EvolutionEngine(
        db,
        artifact_store,
        task_evaluator,
        sandbox,
        llm,
        experiment_id=experiment_id,
        evaluator_version_id=evaluator_version_id,
        environment_version_id=environment_version_id,
        config=eval_config,
        **components,
    )

    if resume:
        result = engine.resume(experiment_id)
    elif settings.evolution.async_pipeline_enabled:
        import asyncio

        from omnievolve.engine.async_engine import AsyncPipelineEngine

        pipeline = AsyncPipelineEngine(engine)
        result = asyncio.run(pipeline.run(initial_code, task_name))
    else:
        result = engine.run(initial_code, task_name)

    _print_result(result, experiment_id)
    db.close()


@app.command()
def status(
    experiment_id: str = typer.Argument(..., help="实验 ID"),
    config: str = typer.Option("omnievolve.toml", "--config", "-c"),
) -> None:
    """查看进化进度、Champion Policy 和健康状态."""
    settings, db, *_ = _bootstrap(config, trusted=True)

    from omnievolve.storage.repositories.experiment_repo import ExperimentRepository

    exp = ExperimentRepository(db).get(experiment_id)
    if exp is None:
        console.print(f"[red]Experiment not found: {experiment_id}[/red]")
        raise typer.Exit(1)

    table = Table(title=f"Experiment {experiment_id}")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("task_name", exp.task_name)
    table.add_row("status", exp.status)
    table.add_row("started_at", str(exp.started_at))
    table.add_row("finished_at", str(exp.finished_at))
    table.add_row("total_tokens", str(exp.total_tokens))
    table.add_row("total_cost_usd", f"${exp.total_cost_usd:.4f}")
    table.add_row("total_compute_sec", f"{exp.total_compute_sec:.1f}")
    table.add_row("champion_policy_id", str(exp.champion_policy_id))
    console.print(table)

    # 候选统计
    row = db.fetchone(
        "SELECT MAX(generation) as max_gen, COUNT(*) as total "
        "FROM candidate WHERE experiment_id = ?",
        (experiment_id,),
    )
    if row and row["total"]:
        console.print(f"\nGenerations: {row['max_gen']}  Candidates: {row['total']}")

    # 最佳候选
    bests = db.fetchall(
        """
        SELECT c.id, c.generation, er.primary_score
        FROM candidate c
        JOIN evaluation_run er ON c.id = er.candidate_id
        WHERE c.experiment_id = ? AND er.status='completed' AND er.passed=1
        ORDER BY er.primary_score DESC LIMIT 5
        """,
        (experiment_id,),
    )
    if bests:
        bt = Table(title="Top Candidates")
        bt.add_column("Candidate ID", style="cyan")
        bt.add_column("Gen", style="yellow")
        bt.add_column("Score", style="green")
        for r in bests:
            bt.add_row(r["id"][:12], str(r["generation"]), f"{r['primary_score']:.4f}")
        console.print(bt)

    _print_policies(db, experiment_id)
    db.close()


@app.command()
def best(
    experiment_id: str = typer.Argument(..., help="实验 ID"),
    config: str = typer.Option("omnievolve.toml", "--config", "-c"),
    show_code: bool = typer.Option(False, "--code", help="打印完整源码"),
) -> None:
    """输出最优 Candidate Artifact."""
    settings, db, artifact_store, *_ = _bootstrap(config, trusted=True)

    row = db.fetchone(
        """
        SELECT c.id, c.artifact_hash, er.primary_score, c.generation
        FROM candidate c
        JOIN evaluation_run er ON c.id = er.candidate_id
        WHERE c.experiment_id = ? AND er.status='completed'
        ORDER BY er.primary_score DESC LIMIT 1
        """,
        (experiment_id,),
    )
    if row is None:
        console.print("[yellow]No evaluated candidates found[/yellow]")
        raise typer.Exit(1)

    console.print(f"Best candidate: [cyan]{row['id']}[/cyan]")
    console.print(f"  generation: {row['generation']}")
    console.print(f"  score: {row['primary_score']:.4f}")
    console.print(f"  artifact_hash: {row['artifact_hash']}")

    if show_code:
        try:
            code = artifact_store.load_snapshot(row["artifact_hash"])
            console.print("\n[bold]Source:[/bold]")
            console.print(code)
        except Exception as e:
            console.print(f"[red]Cannot load artifact: {e}[/red]")
    db.close()


@app.command()
def export(
    experiment_id: str = typer.Argument(..., help="实验 ID"),
    format: str = typer.Option("graphml", "--format", "-f", help="graphml / json"),
    output: str = typer.Option("evolution_graph.graphml", "--output", "-o"),
    config: str = typer.Option("omnievolve.toml", "--config", "-c"),
) -> None:
    """导出进化图或策略谱系."""
    import networkx as nx

    settings, db, *_ = _bootstrap(config, trusted=True)
    from omnievolve.storage.graph_store import GraphStore

    gs = GraphStore(db)
    graph = gs.load_subgraph(experiment_id, include_reference_edges=True)

    # GraphML 不支持 None 值，转换为空字符串
    for _, attrs in graph.nodes(data=True):
        for k, v in list(attrs.items()):
            if v is None:
                attrs[k] = ""
    for _, _, attrs in graph.edges(data=True):
        for k, v in list(attrs.items()):
            if v is None:
                attrs[k] = ""

    if format == "graphml":
        nx.write_graphml(graph, output)
        console.print(
            f"[green]Exported {graph.number_of_nodes()} nodes / "
            f"{graph.number_of_edges()} edges → {output}[/green]"
        )
    elif format == "json":
        data = nx.node_link_data(graph)
        Path(output).write_text(json.dumps(data, indent=2, default=str))
        console.print(f"[green]Exported graph JSON → {output}[/green]")
    else:
        console.print(f"[red]Unknown format: {format}[/red]")
        raise typer.Exit(1)
    db.close()


@app.command()
def policy(
    experiment_id: str = typer.Argument(..., help="实验 ID"),
    config: str = typer.Option("omnievolve.toml", "--config", "-c"),
) -> None:
    """查看 Champion / Challenger 策略谱系."""
    settings, db, *_ = _bootstrap(config, trusted=True)
    _print_policies(db, experiment_id)
    db.close()


@app.command()
def audit(
    experiment_id: str = typer.Argument(..., help="实验 ID"),
    config: str = typer.Option("omnievolve.toml", "--config", "-c"),
    full: bool = typer.Option(False, "--full", help="包含全部候选（默认仅血缘链）"),
    output: str = typer.Option("", "--output", "-o", help="输出 JSON 报告路径"),
) -> None:
    """检查 Artifact 哈希、评估器版本、缺失向量索引，生成端到端审计报告."""
    settings, db, *_ = _bootstrap(config, trusted=True)
    from omnievolve.meta.audit import AuditReportGenerator

    generator = AuditReportGenerator(db, artifact_dir=settings.storage.artifact_dir)
    report = generator.generate(experiment_id, include_all_candidates=full)

    # 摘要表
    table = Table(title=f"Audit: {experiment_id}")
    table.add_column("Check", style="cyan")
    table.add_column("Result", style="white")
    table.add_row("candidates_in_report", str(len(report.candidates)))
    table.add_row("lineage_depth", str(report.lineage_depth))
    table.add_row("total_evaluations", str(report.total_evaluations))
    table.add_row("total_llm_calls", str(report.total_llm_calls))
    table.add_row("policies_tracked", str(len(report.policies)))
    table.add_row("artifact_missing", str(len(report.missing_artifacts)))
    table.add_row("pending_vector_jobs", str(report.missing_vector_indexes))
    table.add_row("expired_leases", str(report.expired_leases))
    console.print(table)

    if report.missing_artifacts:
        console.print("\n[yellow]Missing Artifacts:[/yellow]")
        for h in report.missing_artifacts[:20]:
            console.print(f"  - {h}")
    if report.expired_leases > 0:
        console.print(f"\n[yellow]{report.expired_leases} expired job leases[/yellow]")
    if not report.missing_artifacts and report.expired_leases == 0:
        console.print("[green]✓ No issues found[/green]")

    if output:
        Path(output).write_text(report.to_json(), encoding="utf-8")
        console.print(f"\n[green]Full report → {output}[/green]")
    db.close()


@app.command()
def recover(
    experiment_id: str = typer.Argument(..., help="实验 ID"),
    dry_run: bool = typer.Option(True, "--dry-run/--apply", help="仅扫描不修复"),
    config: str = typer.Option("omnievolve.toml", "--config", "-c"),
) -> None:
    """扫描租约过期任务、未完成 Outbox 和孤立 Artifact."""
    settings, db, *_ = _bootstrap(config, trusted=True)

    expired = db.fetchall(
        "SELECT id, job_type FROM job WHERE experiment_id = ? "
        "AND status='running' AND lease_expires_at < datetime('now')",
        (experiment_id,),
    )
    pending = db.fetchall(
        "SELECT id, entity_id FROM vector_index_job WHERE status='pending' LIMIT 100"
    )

    console.print(f"Expired leases: [yellow]{len(expired)}[/yellow]")
    console.print(f"Pending vector jobs: [yellow]{len(pending)}[/yellow]")

    if dry_run:
        console.print("[dim]Dry run — no changes made. Use --apply to fix.[/dim]")
    else:
        fixed = 0
        for r in expired:
            db.execute(
                "UPDATE job SET status='queued', lease_owner=NULL WHERE id=?",
                (r["id"],),
            )
            fixed += 1
        for r in pending:
            db.execute(
                "UPDATE vector_index_job SET status='failed', "
                "last_error='manual recover' WHERE id=?",
                (r["id"],),
            )
        console.print(f"[green]Reclaimed {fixed} expired leases[/green]")
    db.close()


@app.command()
def migrate(
    config: str = typer.Option("omnievolve.toml", "--config", "-c", help="配置文件路径"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅检查版本，不执行迁移"),
) -> None:
    """执行数据库迁移."""
    from omnievolve.storage.db import Database
    from omnievolve.storage.migrations import CURRENT_VERSION, get_schema_version, migrate

    settings = load_settings(config)
    Path(settings.storage.db_path).parent.mkdir(parents=True, exist_ok=True)
    db = Database(settings.storage.db_path)

    current = get_schema_version(db)
    console.print(f"Current schema version: {current}")
    console.print(f"Target schema version:  {CURRENT_VERSION}")

    if current >= CURRENT_VERSION:
        console.print("[green]Database is up-to-date[/green]")
    else:
        if dry_run:
            console.print(f"[yellow]Would migrate from {current} → {CURRENT_VERSION}[/yellow]")
        else:
            target = migrate(db)
            console.print(f"[green]Migration complete: {current} → {target}[/green]")

    db.close()


@app.command()
def doctor() -> None:
    """环境检测."""
    console.print("[bold]OmniEvolve Doctor[/bold]\n")
    console.print(f"Python: {sys.version}")

    table = Table(title="Dependencies")
    table.add_column("Package", style="cyan")
    table.add_column("Status", style="green")
    for pkg in ["litellm", "networkx", "pydantic", "numpy", "typer", "rich"]:
        try:
            __import__(pkg)
            table.add_row(pkg, "✓ installed")
        except ImportError:
            table.add_row(pkg, "✗ missing")
    console.print(table)

    # Sandbox backends
    from omnievolve.sandbox.registry import get_registry, register_default_backends

    register_default_backends()
    diag = get_registry().doctor()
    bt = Table(title="Sandbox Backends")
    bt.add_column("Backend", style="cyan")
    bt.add_column("Available", style="white")
    for name, info in diag.items():
        bt.add_row(name, "✓" if info.get("available") else "✗")
    console.print(bt)

    # SQLite features
    import sqlite3

    conn = sqlite3.connect(":memory:")
    try:
        fts = conn.execute("SELECT sqlite_compileoption_used('ENABLE_FTS5')").fetchone()
        console.print(f"\nFTS5: {'✓' if fts and fts[0] else '✗'}")
    except Exception:
        console.print("\nFTS5: ?")
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
#  输出辅助
# --------------------------------------------------------------------------- #


def _print_result(result, experiment_id: str) -> None:  # noqa: ANN001
    table = Table(title=f"Evolution Result — {experiment_id}")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("best_candidate_id", str(result.best_candidate_id))
    table.add_row(
        "best_score", f"{result.best_score:.4f}" if result.best_score is not None else "N/A"
    )
    table.add_row("champion_policy_id", str(result.champion_policy_id))
    table.add_row("total_generations", str(result.total_generations))
    table.add_row("total_candidates", str(result.total_candidates))
    table.add_row("total_tokens", str(result.total_tokens))
    table.add_row("total_cost_usd", f"${result.total_cost_usd:.4f}")
    console.print(table)


def _print_policies(db, experiment_id: str) -> None:  # noqa: ANN001
    rows = db.fetchall(
        """
        SELECT id, version, status, risk_level, created_at
        FROM search_policy_version
        WHERE experiment_id = ?
        ORDER BY version
        """,
        (experiment_id,),
    )
    if not rows:
        return
    table = Table(title="Policy Lineage")
    table.add_column("Version", style="yellow")
    table.add_column("ID", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Risk", style="white")
    for r in rows:
        table.add_row(str(r["version"]), r["id"][:12], r["status"], r["risk_level"])
    console.print(table)


def main() -> None:
    """CLI 入口."""
    app()


if __name__ == "__main__":
    main()
