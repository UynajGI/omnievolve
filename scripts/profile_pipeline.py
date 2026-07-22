"""行级性能分析入口 (Scalene).

Usage:
    # 全管线行级 profile (2 代 sort 进化)
    python scripts/profile_pipeline.py --gens 2

    # 指定配置文件
    python scripts/profile_pipeline.py --config configs/sort_optimization.toml --gens 1

    # 输出 HTML 报告
    python scripts/profile_pipeline.py --html profile_report.html --gens 1

    # 只 profile 特定模块
    python scripts/profile_pipeline.py --module engine.novelty --gens 1

需要安装: pip install -e ".[profile]"
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description="OmniEvolve Scalene 行级性能分析")
    parser.add_argument("--gens", type=int, default=1, help="进化代数 (默认 1)")
    parser.add_argument("--config", type=str, default="configs/sort_optimization.toml")
    parser.add_argument("--html", type=str, default=None, help="输出 HTML 报告路径")
    parser.add_argument("--module", type=str, default=None, help="只 profile 特定模块 (如 engine.novelty)")
    parser.add_argument("--cli", action="store_true", default=True, help="终端输出 (默认)")
    args = parser.parse_args()

    # 构建 scalene 命令
    scalene_cmd = [
        sys.executable, "-m", "scalene",
        "--cli",
        "--profile-interval", "0.1",
    ]

    if args.html:
        scalene_cmd.extend(["--html", "--outfile", args.html])

    if args.module:
        # 只 profile 特定文件
        module_path = f"src/omnievolve/{args.module.replace('.', '/')}.py"
        scalene_cmd.extend(["--profile-only", module_path])

    # 目标: 运行 omnievolve CLI
    scalene_cmd.extend([
        "-m", "omnievolve.cli", "run",
        "examples/python_optimization/initial_code.py",
        "-e", "examples.python_optimization.evaluator:SortEvaluator",
        "-c", args.config,
        "--trusted",
        "--gens", str(args.gens),
    ])

    print(f"[profile_pipeline] Running: {' '.join(scalene_cmd)}")
    print(f"[profile_pipeline] Config: {args.config}, Gens: {args.gens}")
    if args.module:
        print(f"[profile_pipeline] Module filter: {args.module}")
    print()

    env = {
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "PATH": "/home/jiangyuan/.local/bin:/usr/bin:/bin",
    }

    import os
    full_env = {**os.environ, **env}

    result = subprocess.run(
        scalene_cmd,
        cwd=str(PROJECT_ROOT),
        env=full_env,
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
