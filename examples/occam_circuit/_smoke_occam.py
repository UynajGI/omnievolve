"""临时管道测试：模拟沙箱跑 #71 候选 + 验证器（不依赖 omnievolve/LLM）。

对 practice-add-n4 与 practice-mul-n4 各跑一遍，检查 test_acc 与门数。
用法: <python> _smoke_occam.py
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
GATE_CAP = 150.0


def run_instance(instance: str) -> int:
    src = HERE / "datasets" / instance
    tmp = Path(tempfile.mkdtemp(prefix="occam_smoke_"))
    shutil.copy2(HERE / "verify_circuit.py", tmp / "verify_circuit.py")
    shutil.copy2(HERE / "initial_code.py", tmp / "main.py")
    # 实例文件以实例无关名挂载
    shutil.copy2(src / "train.csv", tmp / "train.csv")
    shutil.copy2(src / "test_inputs.csv", tmp / "test_inputs.csv")
    shutil.copy2(src / "test_outputs.csv", tmp / "test_outputs.csv")

    t0 = time.time()
    r1 = subprocess.run([PY, "main.py"], cwd=tmp, capture_output=True, text=True, timeout=60)
    t1 = time.time()
    print(f"\n=== {instance} ===")
    print(f"[main.py] rc={r1.returncode} wall={t1 - t0:.1f}s  {r1.stdout.strip()}")
    if r1.returncode != 0:
        print("  stderr:", r1.stderr[-800:])
        return 1

    r2 = subprocess.run([PY, "verify_circuit.py"], cwd=tmp, capture_output=True, text=True, timeout=60)
    if r2.returncode != 0:
        print("[verify] rc!=0 stderr:", r2.stderr[-800:])
        return 1

    verify = None
    for line in reversed(r2.stdout.strip().splitlines()):
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and "test_acc" in obj:
                verify = obj
                break
        except json.JSONDecodeError:
            continue
    print("verify:", json.dumps(verify, indent=2))

    if verify and verify.get("valid"):
        test_acc = verify["test_acc"]
        gates = verify["gates"]
        score = 0.7 * test_acc + 0.3 * max(0.0, 1.0 - gates / GATE_CAP)
        passed = verify["train_acc"] == 1.0 and test_acc >= 0.99
        print(f"=> score={score:.4f}  test_acc={test_acc:.3f}  gates={gates}  passed={passed}")
    else:
        print("=> INVALID")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


def main():
    rc = 0
    for inst in ("practice-add-n4", "practice-mul-n4"):
        rc |= run_instance(inst)
    return rc


if __name__ == "__main__":
    sys.exit(main())
