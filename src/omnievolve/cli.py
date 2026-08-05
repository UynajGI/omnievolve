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

import hashlib
import json
import logging
import os
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


def _load_project_snapshot(root: Path) -> dict[str, str]:
    """读取一个有界、纯文本的多文件项目快照."""
    ignored_dirs = {
        ".git",
        ".omnievolve",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }
    allowed_suffixes = {
        ".cfg",
        ".ini",
        ".js",
        ".json",
        ".md",
        ".py",
        ".pyi",
        ".pyx",
        ".toml",
        ".ts",
        ".txt",
        ".yaml",
        ".yml",
    }
    max_files = 256
    max_file_bytes = 1024 * 1024
    max_total_bytes = 4 * 1024 * 1024
    files: dict[str, str] = {}
    total_bytes = 0

    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in ignored_dirs or part.startswith(".") for part in relative.parts):
            continue
        if not path.is_file() or path.is_symlink() or path.suffix.lower() not in allowed_suffixes:
            continue
        if len(files) >= max_files:
            raise ValueError(f"Project snapshot exceeds {max_files} text files")
        data = path.read_bytes()
        if len(data) > max_file_bytes:
            raise ValueError(f"Project file exceeds 1 MiB: {relative.as_posix()}")
        total_bytes += len(data)
        if total_bytes > max_total_bytes:
            raise ValueError("Project snapshot exceeds 4 MiB")
        try:
            files[relative.as_posix()] = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"Project file is not UTF-8 text: {relative.as_posix()}") from exc

    if "main.py" not in files:
        raise ValueError("A project task must contain a UTF-8 main.py entrypoint")
    return files


def _apply_setting_overrides(settings: OmniEvolveSettings, overrides: list[str] | None) -> None:
    """Apply validated ``section.field=JSON`` overrides to loaded settings."""
    for raw in overrides or []:
        if "=" not in raw:
            raise ValueError(f"Setting override must use key=value: {raw!r}")
        dotted_key, raw_value = raw.split("=", 1)
        parts = [part.strip() for part in dotted_key.split(".") if part.strip()]
        if len(parts) < 2:
            raise ValueError(f"Setting override must include a section: {raw!r}")
        target: Any = settings
        for part in parts[:-1]:
            if not hasattr(target, part):
                raise ValueError(f"Unknown setting path: {dotted_key}")
            target = getattr(target, part)
        field_name = parts[-1]
        if not hasattr(target, field_name):
            raise ValueError(f"Unknown setting path: {dotted_key}")
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError:
            value = raw_value
        setattr(target, field_name, value)


def _bootstrap(
    config_path: str | None,
    *,
    trusted: bool = False,
    settings_overrides: list[str] | None = None,
) -> tuple:
    """加载配置、初始化 DB/migrations、artifact_store、sandbox.

    Returns:
        (settings, db, artifact_store, sandbox)
    """
    settings = load_settings(config_path)
    _apply_setting_overrides(settings, settings_overrides)

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


def _bind_store_for_experiment(db, artifact_store, experiment_id: str):  # noqa: ANN001
    """Bind task-scoped stores (Git) and return the experiment record."""
    from omnievolve.storage.repositories.experiment_repo import ExperimentRepository

    exp = ExperimentRepository(db).get(experiment_id)
    if exp is not None and hasattr(artifact_store, "bind_experiment"):
        artifact_store.bind_experiment(experiment_id, task_name=exp.task_name)
    return exp


def _apply_llm_env_overrides(settings: OmniEvolveSettings) -> dict[str, Any]:
    """Apply documented local test-provider overrides to settings and gateway kwargs."""
    model = os.environ.get("OMNIEVOLVE_LLM_MODEL")
    if model:
        settings.models.heavy = [model]
        settings.models.light = [model]

    max_tokens = settings.models.max_tokens
    raw_max_tokens = os.environ.get("OMNIEVOLVE_LLM_MAX_TOKENS")
    if raw_max_tokens:
        try:
            max_tokens = int(raw_max_tokens)
        except ValueError as exc:
            raise ValueError("OMNIEVOLVE_LLM_MAX_TOKENS must be an integer") from exc
        if max_tokens <= 0:
            raise ValueError("OMNIEVOLVE_LLM_MAX_TOKENS must be positive")
        settings.models.max_tokens = max_tokens

    fallback_endpoints = []
    raw_fallbacks = os.environ.get("OMNIEVOLVE_LLM_FALLBACKS_JSON")
    if raw_fallbacks:
        try:
            fallback_payload = json.loads(raw_fallbacks)
        except json.JSONDecodeError as exc:
            raise ValueError("OMNIEVOLVE_LLM_FALLBACKS_JSON must be valid JSON") from exc
        if not isinstance(fallback_payload, list):
            raise ValueError("OMNIEVOLVE_LLM_FALLBACKS_JSON must be a JSON list")
        from omnievolve.agents.llm_gateway import LLMEndpoint

        for index, item in enumerate(fallback_payload):
            if not isinstance(item, dict) or not isinstance(item.get("model"), str):
                raise ValueError(f"fallback endpoint {index} requires a string model")
            fallback_endpoints.append(
                LLMEndpoint(
                    model=item["model"],
                    api_key=item.get("api_key"),
                    api_base=item.get("api_base"),
                )
            )

    return {
        "api_key": (os.environ.get("OMNIEVOLVE_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")),
        "api_base": (
            os.environ.get("OMNIEVOLVE_LLM_API_BASE") or os.environ.get("OPENAI_BASE_URL")
        ),
        "default_max_tokens": max_tokens,
        # 1.1: 角色级输出预算（网关内钳制到全局上限）
        "role_max_tokens": settings.models.role_max_tokens,
        "fallback_endpoints": fallback_endpoints,
    }


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
    selection_strategy = settings.selection.parent_selector
    if selection_strategy in {"lineage_ucb", "progressive_mcgs"}:
        selection_strategy = "tournament"
    parent_selector = ParentSelector(
        db,
        strategy=selection_strategy,
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
        from omnievolve.utils.embedding import create_embedder

        embedder = create_embedder(
            provider=settings.embedding.code.provider,
            model=settings.embedding.code.model,
            dimension=settings.embedding.code.dimension,
            device=settings.embedding.code.device,
        )

        # 优先 zvec（HNSW ANN），不可用时回退 NumPy
        vector_backend = create_vector_backend(prefer_zvec=True)
        vector_indexer = VectorIndexer(db, vector_backend, embedder)
    except ValueError:
        raise
    except Exception:
        logging.getLogger(__name__).warning(
            "Vector subsystem unavailable; continuing without vector retrieval",
            exc_info=True,
        )

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


def _load_environment_files() -> None:
    """Load local defaults without overriding explicitly supplied process values."""
    load_dotenv(".local.env", override=False)
    load_dotenv(".env", override=False)


@app.command()
def run(
    task: str | None = typer.Argument(None, help="任务描述或初始代码文件路径；--resume 时可省略"),
    config: str = typer.Option("omnievolve.toml", "--config", "-c", help="配置文件路径"),
    evaluator: str = typer.Option(..., "--evaluator", "-e", help="评估器路径 (module:Class)"),
    task_name_override: str | None = typer.Option(
        None,
        "--task-name",
        help="显式任务标识；研究 runner 用它避免不同 initial_code.py 任务混淆",
    ),
    resume: str | None = typer.Option(None, "--resume", help="恢复实验 ID"),
    generations: int | None = typer.Option(None, "--gens", "-g", help="最大代数"),
    trusted: bool = typer.Option(False, "--trusted", help="启用非隔离 subprocess 模式"),
    no_self_evolve: bool = typer.Option(
        False, "--no-self-evolve", help="关闭 Slow Loop 受控策略进化，仅运行 Fast Loop"
    ),
    seed: int | None = typer.Option(None, "--seed", help="确定性实验随机种子"),
    setting: list[str] | None = typer.Option(
        None,
        "--set",
        help="覆盖配置项，格式 section.field=JSON；可重复使用",
    ),
) -> None:
    """启动候选进化；按健康窗口自动运行受控策略进化."""
    from omnievolve.utils.logging import setup_logging

    # 自动加载 .env / .local.env → os.environ。
    # 显式进程环境必须具有最高优先级，便于研究 runner 安全选择模型；
    # 本地私有配置其次，仓库级默认配置最后。
    _load_environment_files()

    setup_logging()
    console.print("[bold green]OmniEvolve[/bold green] - Starting evolution")
    if trusted:
        console.print("[yellow]WARNING: trusted subprocess 模式（非隔离）[/yellow]")

    try:
        settings, db, artifact_store, sandbox = _bootstrap(
            config, trusted=trusted, settings_overrides=setting
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--set") from exc
    llm_kwargs = _apply_llm_env_overrides(settings)
    eval_config = build_evolution_config(settings)
    if generations is not None:
        eval_config.max_generations = generations
    if no_self_evolve:
        eval_config.self_evolve_enabled = False
        console.print("[yellow]Self-evolve (Slow Loop) disabled — fast loop only[/yellow]")
    if seed is not None:
        if seed < 0:
            raise typer.BadParameter("seed must be non-negative", param_hint="--seed")
        eval_config.seed = seed

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
        **llm_kwargs,
    )

    components = _build_engine_components(db, settings, sandbox, llm)

    # 创建或恢复实验
    from omnievolve.storage.repositories.experiment_repo import ExperimentRepository

    exp_repo = ExperimentRepository(db)
    initial_code: str | dict[str, str]
    if resume:
        exp = exp_repo.get(resume)
        if exp is None:
            console.print(f"[red]Experiment not found: {resume}[/red]")
            raise typer.Exit(1)
        experiment_id = resume
        task_name = exp.task_name
        initial_code = ""
    else:
        if task is None:
            console.print("[red]TASK is required unless --resume is used[/red]")
            raise typer.Exit(2)
        task_path = Path(task)
        if task_path.is_dir():
            try:
                initial_code = _load_project_snapshot(task_path)
            except ValueError as exc:
                typer.echo(f"Error: 无法读取项目快照: {exc}", err=True)
                raise typer.Exit(code=1) from exc
            task_name = task_path.name
        elif task_path.exists():
            initial_code = task_path.read_text(encoding="utf-8")
            task_name = task_path.stem
        elif task_path.suffix in (".py", ".toml", ".txt"):
            # 看起来像文件路径但不存在 → 报错
            typer.echo(f"Error: 任务文件不存在: {task}", err=True)
            raise typer.Exit(code=1)
        else:
            initial_code = task
            task_name = task[:60]
        if task_name_override is not None:
            task_name = task_name_override.strip()
            if not task_name:
                raise typer.BadParameter("--task-name must not be empty")

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
        verifier_settings=settings.verifier,
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
    cost_row = db.fetchone(
        """
        SELECT COUNT(*) AS calls, COUNT(cost_usd) AS priced
        FROM llm_call_ledger WHERE experiment_id = ?
        """,
        (experiment_id,),
    )
    cost_known = bool(cost_row and cost_row["calls"] == cost_row["priced"])
    table.add_row(
        "total_cost_usd",
        f"${exp.total_cost_usd:.4f}" if cost_known else "unknown",
    )
    table.add_row("cost_known", str(cost_known).lower())
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
    exp = _bind_store_for_experiment(db, artifact_store, experiment_id)
    if exp is None:
        console.print(f"[red]Experiment not found: {experiment_id}[/red]")
        raise typer.Exit(1)

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
    exp = _bind_store_for_experiment(db, None, experiment_id)
    if exp is None:
        console.print(f"[red]Experiment not found: {experiment_id}[/red]")
        raise typer.Exit(1)
    from omnievolve.storage.graph_store import GraphStore

    gs = GraphStore(db)
    graph = gs.load_subgraph(experiment_id, include_reference_edges=True)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

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
        nx.write_graphml(graph, output_path)
        console.print(
            f"[green]Exported {graph.number_of_nodes()} nodes / "
            f"{graph.number_of_edges()} edges → {output}[/green]"
        )
    elif format == "json":
        data = nx.node_link_data(graph)
        output_path.write_text(
            json.dumps(data, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
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
    exp = _bind_store_for_experiment(db, None, experiment_id)
    if exp is None:
        console.print(f"[red]Experiment not found: {experiment_id}[/red]")
        raise typer.Exit(1)
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
    settings, db, artifact_store, *_ = _bootstrap(config, trusted=True)
    exp = _bind_store_for_experiment(db, artifact_store, experiment_id)
    if exp is None:
        console.print(f"[red]Experiment not found: {experiment_id}[/red]")
        raise typer.Exit(1)
    from omnievolve.meta.audit import AuditReportGenerator

    generator = AuditReportGenerator(
        db,
        artifact_dir=settings.storage.artifact_dir,
        artifact_store=artifact_store,
    )
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
        console.print("[green]OK - No issues found[/green]")

    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report.to_json(), encoding="utf-8")
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
    exp = _bind_store_for_experiment(db, None, experiment_id)
    if exp is None:
        console.print(f"[red]Experiment not found: {experiment_id}[/red]")
        raise typer.Exit(1)

    expired = db.fetchall(
        "SELECT id, job_type FROM job WHERE experiment_id = ? "
        "AND status='running' AND lease_expires_at < datetime('now')",
        (experiment_id,),
    )
    pending = db.fetchall(
        """
        SELECT vij.id, vij.entity_id
        FROM vector_index_job vij
        WHERE vij.status='pending'
          AND (
            (
              vij.entity_type='candidate'
              AND EXISTS (
                SELECT 1 FROM candidate c
                WHERE c.id=vij.entity_id AND c.experiment_id=?
              )
            )
            OR
            (
              vij.entity_type='thought'
              AND EXISTS (
                SELECT 1 FROM thought_record t
                WHERE t.id=vij.entity_id AND t.experiment_id=?
              )
            )
          )
        LIMIT 100
        """,
        (experiment_id, experiment_id),
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


@app.command("research")
def research_benchmark(
    action: str = typer.Argument(
        "plan",
        help=(
            "calibrate、plan、plan-pilot、plan-slow、plan-reference、plan-operator、"
            "plan-selector、plan-context、plan-evaluator、plan-qd、"
            "execute、analyze 或 replay"
        ),
    ),
    output: str = typer.Option(
        ".omnievolve/research/matrix.json", "--output", "-o", help="输出 JSON 路径"
    ),
    seeds: str = typer.Option("0,1,2,3,4", "--seeds", help="5–10 个逗号分隔随机种子"),
    results: str = typer.Option(
        ".omnievolve/research/results.jsonl", "--results", help="analyze 输入 JSONL"
    ),
    calibration: str = typer.Option(
        ".omnievolve/research/calibration.json",
        "--calibration",
        help="冻结候选 evaluator noise calibration JSON",
    ),
    queue_db: str = typer.Option(
        ".omnievolve/research/queue.db", "--queue-db", help="可恢复任务队列数据库"
    ),
    runs_dir: str = typer.Option(
        ".omnievolve/research/runs", "--runs-dir", help="各 run 的隔离产物目录"
    ),
    workers: int = typer.Option(2, "--workers", min=1, help="并发 run 上限"),
    max_attempts: int = typer.Option(3, "--max-attempts", min=1, help="失败重试上限"),
    generations: int = typer.Option(5, "--gens", min=1, help="每个 run 的进化代数"),
    population: int = typer.Option(4, "--population", min=1, help="每代候选数量"),
    eval_repetitions: int = typer.Option(
        3,
        "--eval-repetitions",
        min=3,
        max=10,
        help="无任务校准数据时，每个候选的 evaluator 重复次数",
    ),
    timeout_sec: float = typer.Option(3600.0, "--timeout", min=1.0, help="单 run 超时秒数"),
    task_filter: str | None = typer.Option(
        None,
        "--task",
        help="calibrate/execute 时仅运行指定任务",
    ),
    variant_filter: str | None = typer.Option(None, "--variant", help="execute 时仅运行指定变体"),
    seed_limit: int | None = typer.Option(
        None, "--seed-limit", min=1, help="execute 时每个 cell 仅取前 N 个种子"
    ),
    run_id: str | None = typer.Option(None, "--run-id", help="replay 的 research run ID"),
    repetition: int = typer.Option(0, "--repetition", min=0, help="replay 的重复编号"),
    execute_replay: bool = typer.Option(
        False, "--execute-replay", help="通过严格校验后在新隔离目录实际重跑"
    ),
    include_cost_metric: bool = typer.Option(
        True,
        "--include-cost/--exclude-cost",
        help="analyze 时是否把已知成本作为 pilot gate 必需指标",
    ),
    deterministic_replay_passed: bool = typer.Option(
        False,
        "--deterministic-replay-passed",
        help="analyze 时确认 FakeLLM deterministic resume 不变量已通过",
    ),
) -> None:
    """建立研究矩阵，或聚合已完成运行并计算置信区间."""
    from omnievolve.research.matrix import (
        PILOT_TASK_NAMES,
        PILOT_TASKS,
        build_context_matrix,
        build_default_matrix,
        build_evaluator_matrix,
        build_operator_portfolio_matrix,
        build_pilot_matrix,
        build_qd_archive_matrix,
        build_reference_credit_matrix,
        build_selector_matrix,
        build_slow_loop_matrix,
        load_calibration_repetitions,
        summarize_results,
        write_manifest,
    )

    if action == "calibrate":
        from omnievolve.research.runner import (
            CalibrationRunSettings,
            EvaluatorNoiseCalibrator,
        )

        calibration_tasks = PILOT_TASKS
        if task_filter:
            calibration_tasks = tuple(task for task in PILOT_TASKS if task.name == task_filter)
            if not calibration_tasks:
                raise typer.BadParameter(
                    f"pilot calibration task not found: {task_filter}",
                    param_hint="--task",
                )
        calibrator = EvaluatorNoiseCalibrator(
            CalibrationRunSettings(
                repo_root=Path.cwd(),
                runs_dir=Path(runs_dir),
                timeout_sec=timeout_sec,
                trusted=True,
            )
        )
        try:
            calibration_report = calibrator.run(tasks=calibration_tasks)
        except (RuntimeError, ValueError) as exc:
            raise typer.BadParameter(str(exc), param_hint="calibrate") from exc
        calibration_path = Path(calibration)
        calibration_path.parent.mkdir(parents=True, exist_ok=True)
        calibration_path.write_text(
            json.dumps(calibration_report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        console.print(
            f"[green]Evaluator calibration complete: "
            f"{len(calibration_tasks)} tasks → {calibration_path}[/green]"
        )
        return

    if action in {
        "plan",
        "plan-pilot",
        "plan-slow",
        "plan-reference",
        "plan-operator",
        "plan-selector",
        "plan-context",
        "plan-evaluator",
        "plan-qd",
    }:
        try:
            seed_values = tuple(int(value.strip()) for value in seeds.split(",") if value.strip())
            if action == "plan":
                jobs = build_default_matrix(
                    seeds=seed_values,
                    eval_repetitions=eval_repetitions,
                )
            elif action == "plan-pilot":
                if len(seed_values) < 3:
                    raise ValueError("pilot requires at least three seeds")
                calibration_path = Path(calibration)
                if not calibration_path.exists():
                    raise ValueError(
                        "pilot requires evaluator calibration; run "
                        "`omnievolve research calibrate` first"
                    )
                calibration_bytes = calibration_path.read_bytes()
                calibration_payload = json.loads(calibration_bytes)
                from omnievolve.research.runner import (
                    validate_calibration_report,
                )

                calibration_issues = validate_calibration_report(
                    calibration_payload,
                    Path.cwd(),
                )
                if calibration_issues:
                    raise ValueError(
                        "pilot calibration provenance is stale or incomplete: "
                        + "; ".join(calibration_issues)
                    )
                calibrated_repetitions = load_calibration_repetitions(
                    calibration_path,
                    required_tasks=PILOT_TASK_NAMES,
                )
                jobs = build_pilot_matrix(
                    seeds=seed_values[:3],
                    eval_repetitions=calibrated_repetitions,
                )
            elif action == "plan-slow":
                jobs = build_slow_loop_matrix(
                    seeds=seed_values,
                    eval_repetitions=eval_repetitions,
                )
            elif action == "plan-reference":
                jobs = build_reference_credit_matrix(
                    seeds=seed_values,
                    eval_repetitions=eval_repetitions,
                )
            elif action == "plan-operator":
                jobs = build_operator_portfolio_matrix(
                    seeds=seed_values,
                    eval_repetitions=eval_repetitions,
                )
            elif action == "plan-selector":
                jobs = build_selector_matrix(
                    seeds=seed_values,
                    eval_repetitions=eval_repetitions,
                )
            elif action == "plan-context":
                jobs = build_context_matrix(
                    seeds=seed_values,
                    eval_repetitions=eval_repetitions,
                )
            elif action == "plan-evaluator":
                jobs = build_evaluator_matrix(seeds=seed_values)
            else:
                jobs = build_qd_archive_matrix(
                    seeds=seed_values,
                    eval_repetitions=eval_repetitions,
                )
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--seeds") from exc
        metadata = {}
        if action == "plan-pilot":
            metadata = {
                "calibration_path": str(Path(calibration).resolve()),
                "calibration_sha256": hashlib.sha256(calibration_bytes).hexdigest(),
                "calibration_required": True,
                "calibration_all_converged": bool(calibration_payload.get("all_converged")),
                "calibration_minimum_effect": calibration_payload.get("minimum_effect"),
            }
        path = write_manifest(jobs, output, metadata=metadata)
        variant_count = len({job.variant.name for job in jobs})
        task_count = len({job.task.name for job in jobs})
        console.print(
            f"[green]Research matrix: {task_count} tasks × {variant_count} variants × "
            f"{len(seed_values)} seeds = {len(jobs)} runs → {path}[/green]"
        )
        return

    if action == "execute":
        from omnievolve.research.runner import (
            ResearchBenchmarkRunner,
            ResearchRunSettings,
            load_manifest_jobs,
        )

        matrix_path = Path(output)
        if not matrix_path.exists():
            raise typer.BadParameter(f"matrix file not found: {output}", param_hint="--output")
        jobs = load_manifest_jobs(matrix_path)
        if task_filter:
            jobs = [job for job in jobs if job.task.name == task_filter]
        if variant_filter:
            jobs = [job for job in jobs if job.variant.name == variant_filter]
        if seed_limit is not None:
            allowed = sorted({job.seed for job in jobs})[:seed_limit]
            jobs = [job for job in jobs if job.seed in allowed]
        if not jobs:
            raise typer.BadParameter("no jobs match the execute filters")
        runner = ResearchBenchmarkRunner(
            ResearchRunSettings(
                repo_root=Path.cwd(),
                results_path=Path(results),
                runs_dir=Path(runs_dir),
                generations=generations,
                population_size=population,
                timeout_sec=timeout_sec,
                trusted=True,
            ),
            max_concurrency=workers,
            max_attempts=max_attempts,
        )
        report = runner.run(jobs, queue_db)
        console.print(
            "[green]"
            f"Research queue idle: completed={report.completed}, "
            f"failed={report.failed}, retried={report.retried} → {results}"
            "[/green]"
        )
        return

    if action == "analyze":
        result_path = Path(results)
        if not result_path.exists():
            raise typer.BadParameter(f"results file not found: {results}", param_hint="--results")
        records = [
            json.loads(line)
            for line in result_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        analysis_report = summarize_results(
            records,
            include_cost_metric=include_cost_metric,
            deterministic_replay_passed=deterministic_replay_passed,
        )
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(analysis_report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        console.print(f"[green]Aggregated {len(records)} records → {output_path}[/green]")
        return

    if action == "replay":
        if not run_id:
            raise typer.BadParameter("replay requires --run-id", param_hint="--run-id")
        from omnievolve.research.runner import strict_replay

        try:
            replay_result = strict_replay(
                runs_dir,
                run_id,
                repetition=repetition,
                execute=execute_replay,
                timeout_sec=timeout_sec,
            )
        except (FileNotFoundError, RuntimeError) as exc:
            raise typer.BadParameter(str(exc), param_hint="--run-id") from exc
        console.print_json(json.dumps(replay_result, ensure_ascii=False))
        return

    raise typer.BadParameter(
        "action must be calibrate, plan, plan-pilot, plan-reference, "
        "plan-operator, plan-qd, execute, analyze, or replay",
        param_hint="ACTION",
    )


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
            table.add_row(pkg, "[green]OK[/green]")
        except ImportError:
            table.add_row(pkg, "[red]MISSING[/red]")
    console.print(table)

    # Sandbox backends
    from omnievolve.sandbox.registry import get_registry, register_default_backends

    register_default_backends()
    diag = get_registry().doctor()
    bt = Table(title="Sandbox Backends")
    bt.add_column("Backend", style="cyan")
    bt.add_column("Available", style="white")
    for name, info in diag.items():
        bt.add_row(name, "[green]OK[/green]" if info.get("available") else "[red]--[/red]")
    console.print(bt)

    # SQLite features
    import sqlite3

    conn = sqlite3.connect(":memory:")
    try:
        fts = conn.execute("SELECT sqlite_compileoption_used('ENABLE_FTS5')").fetchone()
        console.print(f"\nFTS5: {'[green]OK[/green]' if fts and fts[0] else '[red]MISSING[/red]'}")
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
    table.add_row(
        "total_cost_usd",
        f"${result.total_cost_usd:.4f}" if result.cost_known else "unknown",
    )
    table.add_row("cost_known", str(result.cost_known).lower())
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
