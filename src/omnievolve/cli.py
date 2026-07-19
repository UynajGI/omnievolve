"""OmniEvolve CLI.

S9-09: 实现 CLI run/resume/status/best
S9-10: 实现 CLI export/audit/doctor
"""

from __future__ import annotations

import sys

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="omnievolve",
    help="OmniEvolve - 受控元进化框架",
    add_completion=False,
)
console = Console()


@app.command()
def run(
    task: str = typer.Argument(..., help="任务描述或初始代码文件路径"),
    config: str = typer.Option("omnievolve.toml", "--config", "-c", help="配置文件路径"),
    evaluator: str = typer.Option(..., "--evaluator", "-e", help="评估器路径 (module:Class)"),
    resume: str | None = typer.Option(None, "--resume", help="恢复实验 ID"),
    generations: int | None = typer.Option(None, "--gens", "-g", help="最大代数"),
    trusted: bool = typer.Option(False, "--trusted", help="启用非隔离 subprocess 模式"),
) -> None:
    """启动候选进化."""
    console.print("[bold green]OmniEvolve[/bold green] - Starting evolution")
    console.print(f"Task: {task}")
    console.print(f"Evaluator: {evaluator}")

    if trusted:
        console.print("[yellow]WARNING: Using trusted subprocess mode (NOT SECURE)[/yellow]")

    if resume:
        console.print(f"Resuming experiment: {resume}")

    # TODO: 实现完整进化循环
    console.print("[dim]Evolution engine not yet fully implemented[/dim]")


@app.command()
def status(experiment_id: str = typer.Argument(..., help="实验 ID")) -> None:
    """查看进化进度."""
    console.print(f"Experiment: {experiment_id}")
    # TODO: 从数据库读取状态
    console.print("[dim]Status command not yet implemented[/dim]")


@app.command()
def best(experiment_id: str = typer.Argument(..., help="实验 ID")) -> None:
    """输出最优候选."""
    console.print(f"Best candidate for: {experiment_id}")
    # TODO: 从数据库读取最佳候选
    console.print("[dim]Best command not yet implemented[/dim]")


@app.command()
def export(
    experiment_id: str = typer.Argument(..., help="实验 ID"),
    format: str = typer.Option("graphml", "--format", "-f", help="导出格式"),
    output: str | None = typer.Option(None, "--output", "-o", help="输出路径"),
) -> None:
    """导出进化图或策略谱系."""
    console.print(f"Exporting {experiment_id} as {format}")
    # TODO: 实现导出
    console.print("[dim]Export command not yet implemented[/dim]")


@app.command()
def policy(experiment_id: str = typer.Argument(..., help="实验 ID")) -> None:
    """查看 Champion / Challenger 策略."""
    console.print(f"Policy for: {experiment_id}")
    # TODO: 从数据库读取策略
    console.print("[dim]Policy command not yet implemented[/dim]")


@app.command()
def audit(experiment_id: str = typer.Argument(..., help="实验 ID")) -> None:
    """检查 Artifact 哈希、评估器版本和缺失向量索引."""
    console.print(f"Auditing: {experiment_id}")
    # TODO: 实现审计
    console.print("[dim]Audit command not yet implemented[/dim]")


@app.command()
def recover(
    experiment_id: str = typer.Argument(..., help="实验 ID"),
    dry_run: bool = typer.Option(True, "--dry-run/--apply", help="仅扫描不修复"),
) -> None:
    """扫描租约过期任务、未完成 Outbox 和孤立 Artifact."""
    console.print(f"Recovering: {experiment_id}")
    if dry_run:
        console.print("[yellow]Dry run mode - no changes will be made[/yellow]")
    # TODO: 实现恢复
    console.print("[dim]Recover command not yet implemented[/dim]")


@app.command()
def doctor() -> None:
    """环境检测."""
    console.print("[bold]OmniEvolve Doctor[/bold]\n")

    # 检查 Python 版本
    console.print(f"Python: {sys.version}")

    # 检查依赖
    table = Table(title="Dependencies")
    table.add_column("Package", style="cyan")
    table.add_column("Status", style="green")

    packages = ["litellm", "networkx", "pydantic", "numpy", "typer", "rich"]
    for pkg in packages:
        try:
            __import__(pkg)
            table.add_row(pkg, "✓ installed")
        except ImportError:
            table.add_row(pkg, "✗ missing")

    console.print(table)

    # 检查 Docker
    try:
        import docker

        client = docker.from_env()
        client.ping()
        console.print("\nDocker: [green]✓ available[/green]")
    except Exception:
        console.print("\nDocker: [yellow]✗ not available[/yellow]")


def main() -> None:
    """CLI 入口."""
    app()


if __name__ == "__main__":
    main()
