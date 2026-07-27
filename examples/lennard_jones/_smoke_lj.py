"""临时管道测试：模拟 OmniEvolve 沙箱跑 #117 候选 + 验证器（不依赖 omnievolve/LLM）。

用法: <python> _smoke_lj.py
"""
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).parent
PY = sys.executable


def main():
    tmp = Path(tempfile.mkdtemp(prefix="lj_smoke_"))
    print(f"exec_dir = {tmp}")
    # 模拟沙箱挂载：按 basename 复制到 exec_dir
    shutil.copy2(HERE / "lj_ref.py", tmp / "lj_ref.py")
    shutil.copy2(HERE / "verify_lj.py", tmp / "verify_lj.py")
    shutil.copy2(HERE / "initial_code.py", tmp / "main.py")  # 候选规范名 main.py

    # 步骤 1：候选
    t0 = time.time()
    r1 = subprocess.run([PY, "main.py"], cwd=tmp, capture_output=True, text=True, timeout=180)
    t1 = time.time()
    print(f"[main.py] rc={r1.returncode}  wall={t1 - t0:.1f}s")
    print("  stdout:", r1.stdout.strip())
    if r1.returncode != 0:
        print("  stderr:", r1.stderr[-800:])
        return 1

    # 步骤 2：验证器
    r2 = subprocess.run([PY, "verify_lj.py"], cwd=tmp, capture_output=True, text=True, timeout=30)
    print(f"[verify_lj.py] rc={r2.returncode}")
    if r2.returncode != 0:
        print("  stderr:", r2.stderr[-800:])
        return 1

    # 解析验证器最后一行 JSON
    verify = None
    for line in reversed(r2.stdout.strip().splitlines()):
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and "energy_recomputed" in obj:
                verify = obj
                break
        except json.JSONDecodeError:
            continue
    print("verify output:", json.dumps(verify, indent=2))

    # 复算评估器评分公式
    E_BASE, E_GM, GM_TOL = -150.0, -173.928426, 1e-3
    if verify and verify.get("valid"):
        e = verify["energy_recomputed"]
        perf = max(0.0, min(1.0, (E_BASE - e) / (E_BASE - E_GM)))
        score = 0.5 + 0.5 * perf
        passed = e <= E_GM + GM_TOL
        print(f"=> score={score:.4f}  perf={perf:.4f}  passed={passed}")
    else:
        print("=> INVALID (score 0)")

    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
