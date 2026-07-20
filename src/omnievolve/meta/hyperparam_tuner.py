"""贝叶斯超参数优化器.

GP + Expected Improvement，替代硬编码规则做 Slow Loop 搜索参数调优。
参数空间小（5-10 个），单次评估代价高，贝叶斯优化天然适合。

S9: Bayesian optimization for search hyperparameters.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ParamSpec:
    """单个参数的搜索空间定义."""

    name: str
    kind: str  # "float" | "int" | "choice"
    low: float = 0.0
    high: float = 1.0
    choices: list[Any] | None = None  # for "choice" kind
    step: float | None = None  # for float discretization


@dataclass
class TrialRecord:
    """单次试验记录."""

    params: dict[str, Any]
    score: float
    generation: int = 0


# 默认搜索空间 — SearchPolicyGenome 中可数值化的参数
DEFAULT_PARAM_SPACE = [
    ParamSpec("mutation_point_weight", "float", 0.1, 0.8),
    ParamSpec("mutation_crossover_weight", "float", 0.05, 0.5),
    ParamSpec("mutation_rewrite_weight", "float", 0.05, 0.5),
    ParamSpec("retrieval_budget", "int", 4, 20),
    ParamSpec("memory_l0_weight", "float", 0.5, 1.0),
    ParamSpec("memory_l3_weight", "float", 0.1, 0.8),
    ParamSpec("memory_l4_weight", "float", 0.05, 0.5),
]


class BayesianTuner:
    """Gaussian Process + Expected Improvement 贝叶斯优化器.

    增量式：每次 suggest() 返回 EI 最优参数，update() 记录结果。
    """

    def __init__(
        self,
        param_space: list[ParamSpec] | None = None,
        *,
        n_initial: int = 5,
        exploration_xi: float = 0.01,
        random_state: int | None = 42,
    ) -> None:
        self._space = param_space or DEFAULT_PARAM_SPACE
        self._n_initial = n_initial
        self._xi = exploration_xi
        self._rng = np.random.RandomState(random_state)
        self._trials: list[TrialRecord] = []
        self._gp = None  # 延迟导入避免硬依赖
        self._bounds = self._compute_bounds()
        self._int_indices = [i for i, p in enumerate(self._space) if p.kind == "int"]
        self._y_best: float | None = None

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def suggest(self) -> dict[str, Any]:
        """建议下一组参数.

        Returns:
            {param_name: value} 字典
        """
        if len(self._trials) < self._n_initial:
            return self._random_sample()

        return self._ei_suggest()

    def update(self, params: dict[str, Any], score: float, generation: int = 0) -> None:
        """记录试验结果."""
        record = TrialRecord(params=params, score=score, generation=generation)
        self._trials.append(record)

        # 更新 best
        if self._y_best is None or score > self._y_best:
            self._y_best = score

        logger.info(
            "BayesianTuner trial %d: score=%.4f, best=%.4f",
            len(self._trials),
            score,
            self._y_best,
        )

    def get_best(self) -> TrialRecord | None:
        """获取历史最佳."""
        if not self._trials:
            return None
        return max(self._trials, key=lambda t: t.score)

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息."""
        scores = [t.score for t in self._trials]
        return {
            "n_trials": len(self._trials),
            "best_score": self._y_best,
            "mean_score": float(np.mean(scores)) if scores else 0.0,
            "std_score": float(np.std(scores)) if len(scores) > 1 else 0.0,
            "converged": len(scores) >= 3 and np.std(scores[-3:]) < 0.001
            if len(scores) >= 3
            else False,
        }

    # ------------------------------------------------------------------ #
    #  Internal
    # ------------------------------------------------------------------ #

    def _compute_bounds(self) -> np.ndarray:
        lows = [p.low for p in self._space]
        highs = [p.high for p in self._space]
        return np.array([lows, highs])

    def _random_sample(self) -> dict[str, Any]:
        """随机采样（初始探索阶段）."""
        point = self._rng.uniform(self._bounds[0], self._bounds[1])

        for idx in self._int_indices:
            point[idx] = round(point[idx])

        return self._vector_to_params(point)

    def _ei_suggest(self) -> dict[str, Any]:
        """Expected Improvement 采样."""
        X = np.array([self._params_to_vector(t.params) for t in self._trials])
        y = np.array([t.score for t in self._trials])

        try:
            gp = self._fit_gp(X, y)
        except Exception:
            logger.warning("GP fit failed, falling back to random", exc_info=True)
            return self._random_sample()

        y_best = self._y_best or max(y)

        # 多起点随机搜索最大化 EI
        n_restarts = 20
        candidates = self._rng.uniform(
            self._bounds[0], self._bounds[1], size=(n_restarts, len(self._space))
        )
        ei_values = np.array([self._expected_improvement(x, gp, y_best) for x in candidates])
        best_idx = int(np.argmax(ei_values))
        point = candidates[best_idx]

        # 处理整数参数
        for idx in self._int_indices:
            point[idx] = round(point[idx])

        return self._vector_to_params(point)

    def _fit_gp(self, X: np.ndarray, y: np.ndarray):
        """拟合 Gaussian Process."""
        from sklearn.gaussian_process import GaussianProcessRegressor
        from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel

        # 标准化 y
        y_mean = float(np.mean(y))
        y_std = float(np.std(y)) or 1.0
        y_norm = (y - y_mean) / y_std

        kernel = ConstantKernel(1.0) * RBF(length_scale=0.5) + WhiteKernel(noise_level=0.01)
        gp = GaussianProcessRegressor(
            kernel=kernel,
            n_restarts_optimizer=5,
            random_state=self._rng.randint(0, 2**31),
        )
        gp.fit(X, y_norm)
        return gp

    @staticmethod
    def _expected_improvement(
        x: np.ndarray,
        gp: Any,
        y_best: float,
    ) -> float:
        """计算 Expected Improvement."""
        from scipy.stats import norm

        x_2d = x.reshape(1, -1)
        mu, sigma = gp.predict(x_2d, return_std=True)
        mu = float(mu[0])
        sigma = float(sigma[0])

        if sigma < 1e-9:
            return 0.0

        improvement = mu - y_best
        Z = improvement / sigma
        ei = improvement * norm.cdf(Z) + sigma * norm.pdf(Z)
        return float(max(ei, 0.0))

    # ------------------------------------------------------------------ #
    #  Param ↔ Vector conversion
    # ------------------------------------------------------------------ #

    def _params_to_vector(self, params: dict[str, Any]) -> np.ndarray:
        """参数字典 → 归一化向量."""
        vec = np.zeros(len(self._space))
        for i, spec in enumerate(self._space):
            v = params.get(spec.name, (spec.low + spec.high) / 2)
            if spec.kind == "choice" and spec.choices:
                v = spec.choices.index(v) / max(len(spec.choices) - 1, 1)
            else:
                v = (v - spec.low) / max(spec.high - spec.low, 1e-9)
                v = max(0.0, min(1.0, v))
            vec[i] = v
        return vec

    def _vector_to_params(self, vec: np.ndarray) -> dict[str, Any]:
        """归一化向量 → 参数字典."""
        params: dict[str, Any] = {}
        for i, spec in enumerate(self._space):
            v = float(vec[i])
            v = max(0.0, min(1.0, v))
            if spec.kind == "choice" and spec.choices:
                idx = int(round(v * (len(spec.choices) - 1)))
                params[spec.name] = spec.choices[max(0, min(idx, len(spec.choices) - 1))]
            elif spec.kind == "int":
                val = int(round(spec.low + v * (spec.high - spec.low)))
                params[spec.name] = max(int(spec.low), min(val, int(spec.high)))
            else:
                val = spec.low + v * (spec.high - spec.low)
                if spec.step:
                    val = round(val / spec.step) * spec.step
                params[spec.name] = max(spec.low, min(val, spec.high))
        return params

    # ------------------------------------------------------------------ #
    #  Genome integration
    # ------------------------------------------------------------------ #

    def genome_to_params(self, genome: Any) -> dict[str, Any]:
        """从 SearchPolicyGenome 提取数值参数."""
        mm = getattr(genome, "mutation_mix", {})
        mw = getattr(genome, "memory_scope_weights", {})
        return {
            "mutation_point_weight": mm.get("point", 0.5),
            "mutation_crossover_weight": mm.get("crossover", 0.3),
            "mutation_rewrite_weight": mm.get("rewrite", 0.2),
            "retrieval_budget": getattr(genome, "retrieval_budget", 8),
            "memory_l0_weight": mw.get("L0", 1.0),
            "memory_l3_weight": mw.get("L3", 0.4),
            "memory_l4_weight": mw.get("L4", 0.2),
        }

    def params_to_genome_updates(self, params: dict[str, Any]) -> dict[str, Any]:
        """参数字典 → SearchPolicyGenome 可用的更新字典."""
        updates: dict[str, Any] = {}

        # mutation_mix
        mm = {}
        if "mutation_point_weight" in params:
            mm["point"] = params["mutation_point_weight"]
        if "mutation_crossover_weight" in params:
            mm["crossover"] = params["mutation_crossover_weight"]
        if "mutation_rewrite_weight" in params:
            mm["rewrite"] = params["mutation_rewrite_weight"]
        if mm:
            # normalize
            total = sum(mm.values())
            if total > 0:
                mm = {k: round(v / total, 3) for k, v in mm.items()}
            updates["mutation_mix"] = mm

        # retrieval_budget
        if "retrieval_budget" in params:
            updates["retrieval_budget"] = int(params["retrieval_budget"])

        # memory_scope_weights
        mw = {}
        if "memory_l0_weight" in params:
            mw["L0"] = params["memory_l0_weight"]
        if "memory_l3_weight" in params:
            mw["L3"] = params["memory_l3_weight"]
        if "memory_l4_weight" in params:
            mw["L4"] = params["memory_l4_weight"]
        if mw:
            # 保留下来的权重（L1, L2 不变）
            mw.setdefault("L1", 0.9)
            mw.setdefault("L2", 0.6)
            updates["memory_scope_weights"] = mw

        return updates
