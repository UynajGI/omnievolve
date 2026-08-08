"""SSWevolve 领域插件 (极涡指数预报).

提供 SSW 低阶随机动力学预报场景的领域提示 (Domain Hints):
- 前 5 天贴线目标 (f_early5) 与"欠振幅阻尼振荡"诊断 (2026-08-07)
- base_scale 基座漂移乘子经验 (v2.4.0, 专家拍板放开)
- 10 状态变量完整保留约束 (专家意见 2)
- 边级跨分支重组 (2026-08-08, 档 2): 从 High-Scoring Programs 提取高分边的
  结构化借鉴方法论 —— 配合架构档 1 (reference-edge 回流) 已注入的完整代码

领域知识随进化自动注入 Director 提示词的 "## Domain Hints" 段,
无需人工在轮次间改种子文件 —— 路线 2 (提示词随 evolve 演化) 的载体。
"""

from __future__ import annotations

from typing import Any

from omnievolve.eval.task_evaluator import CandidateArtifact, EvalOutput
from omnievolve.plugins.base import BasePlugin

SSWEVOLVE_KEYWORDS = (
    "sswevolve",
    "ssw",
    "polar vortex",
    "stratosphere",
    "极涡",
    "平流层",
    "um",
    "u_m",
)


class SSWEvolvePlugin(BasePlugin):
    """SSWevolve 领域插件.

    领域提示涵盖 (2026-08-07/08 诊断结论 + 专家意见):
    - 前 5 天贴线 = 幅度恢复问题 (欠振幅 10-21%), 非相位问题
    - base_scale 乘子 (a2/g1/g2, [0.5,2.0]) 是基座漂移杠杆 (R13 实证 0.7→0.8)
    - 10 变量完整保留
    - 边级跨分支重组 (档 2, 2026-08-08)
    """

    name = "sswevolve"
    version = "0.2.0"

    DOMAIN_HINTS = [
        "核心目标：SSW 发生时 U_M (极涡指数) 迅速下降；正常态好预报不稀奇",
        "前 5 天贴线 (f_early5) 的机理诊断 (2026-08-07)：模型与观测相关极高 "
        "(corr 0.98→0.85)，但**幅度系统性衰减**——std_model/std_obs 从 0.98 "
        "单调降到 0.79 (lead1→10)，向气候态收缩。**R12 教训：lin(U_M) 自反馈"
        "是死路 (放大噪声, SSR 爆表)**。正确解法：增强 bilin(mA1,U_M) 强事件响应"
        "或加 abs05(U_M) 亚线性幅度边——不放大噪声的幅度补偿。目标 "
        "std_model/std_obs≈1.0，别加过头 (gate 会拦 cov80/SSR)",
        "base_scale 基座漂移乘子 (v2.4.0)：GRAPH 顶层可选字段，对 U_M/U_L/U_U 的 "
        "a2 (自回归恢复率)/g1/g2 (拖曳) 输出 [0.5,2.0] 乘子。**R13 实证: a2×0.8 "
        "优于 0.7 (cov80 0.789→0.799 + f_ssw 双改善)**, 可探索 0.8-0.9 区间或"
        "多系数联合 (U_M a2 + U_L/U_U g1/g2)；只缩放不改结构",
        "10 个状态变量 (U_L,U_M,U_U,Ψ1,Ψ2,H1,H2,S) 全部重要：evolve 不得删减 "
        "方程变量数 (vars gate ≥6/9, 记忆节点不算物理变量)",
        "split 型 SSW 是盲区 (快速崩涡)：重点攻关波2 (mA2) 耦合；displacement 型 "
        "已有 bilin(mA1,U_M) 崩塌 motif",
        "评估器会拦过度发散 (SSR 容差 0.15 且发散侧 ×2) 与集合平均被拉平 "
        "(signal_ratio 阈值 0.8)——成员不能开局即散，但也不能过于收紧",
        "【边级跨分支重组 (档 2, 2026-08-08)】High-Scoring Programs 段里的高分"
        "代码是其他搜索线的成果 (reference-edge 回流)——**不要整段复制**, 要"
        "做边级借鉴：① 提取参考代码里 to=U_M 的边, 观察它的 fn/from/coef 组合; "
        "② 移植: 把参考边原样加入当前图 (注意同名 coef 会合并共享系数); "
        "③ 替换: 用参考边替换当前图中效果弱的边; ④ 组合: 两条参考边 + 新 coef "
        "名生成新通路。R13/R14 突破都来自 U_M 边的微调 (pen_ssr 3.97→3.88, "
        "cov80 破 0.8)——边级组合优先于大改结构",
    ]

    RAG_CORPUS = [
        {
            "topic": "early-fit amplitude contraction",
            "content": (
                "f_early5 (前 5 天集合平均 RMSE) 的 5.57 平台根因是确定性动力学"
                "幅度收缩：std_model/std_obs 0.98→0.79，相位正确 (corr≥0.85)。"
                "修法是 CLOSURE 加法项补偿幅度 (lin/bilin)，不是调噪声或 base_scale。"
            ),
        },
        {
            "topic": "base_scale multipliers",
            "content": (
                "base_scale 是 v2.4.0 放开的基座漂移乘子 (a2/g1/g2, 0.5-2.0)。"
                "U_M a2×0.75 曾把 f_early5 从 5.570 降到 5.429；R13 实证 a2×0.8 最优"
                " (0.8999, cov80 0.799)；R14 保持 0.8 + 边微调 → 0.9072。"
                "单系数微调已达甜区，多系数联合或加法项是下一步。"
            ),
        },
        {
            "topic": "cross-branch edge recombination",
            "content": (
                "跨分支借鉴的正确姿势 (档 2)：High-Scoring Programs 是其他搜索线的"
                "成果，做**边级重组**而非整段复制。三操作：移植 (参考边原样加入)、"
                "替换 (用参考边换弱边)、组合 (两条参考边 + 新 coef 名)。"
                "U_M 相关边优先——R13/R14 突破全部来自 U_M 边微调。"
            ),
        },
    ]

    def get_domain_hints(self, task_description: str) -> list[str]:
        """返回 SSW 领域提示 (任务描述含 sswevolve/极涡等关键词时)."""
        low = task_description.lower()
        if any(kw in low for kw in SSWEVOLVE_KEYWORDS):
            return self.DOMAIN_HINTS
        return []

    def get_rag_corpus(self) -> list[dict] | None:
        """返回 SSW 领域 RAG 语料."""
        return self.RAG_CORPUS

    def enrich_evaluation(
        self,
        candidate: CandidateArtifact,
        output: EvalOutput,
    ) -> dict[str, Any]:
        """补充评估指标 (只补充, 不改主分)."""
        return {}
