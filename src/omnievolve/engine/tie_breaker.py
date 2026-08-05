"""2.4: 离散集成 tie-breaker（logprobs-free）.

改进计划 §2.4 — 任务分数打平（|Δ| ≤ tolerance）时，用 K 次 A/B 成对比较
（奇偶交换位置防位置偏差）聚合偏好，给 ``search_score`` 加**有界** bonus，
影响 LineageUCB 的 relative-gain credit。

约束（设计红线）：
- 独立诚实模式：不伪装成 logprob 概率，不触碰 ``passed``/``primary_score``；
- bonus 有界（``bonus_cap``），只作用于搜索信用路径；
- 偏好证据写入 candidate metrics（``tie_break_*``），可审计。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from omnievolve.agents.llm_gateway import LLMGateway

logger = logging.getLogger(__name__)

TIEBREAK_SYSTEM_PROMPT = (
    "You are an impartial code judge in an evolutionary code optimization system.\n"
    "Given two candidate implementations (A and B) of the same task, decide which is "
    "better overall — considering correctness, efficiency, robustness and maintainability.\n"
    "Reply with exactly 'A' or 'B', nothing else."
)

TIEBREAK_USER_TEMPLATE = """Task: {task}

Candidate A (score={score_a}):
```python
{code_a}
```

Candidate B (score={score_b}):
```python
{code_b}
```

Which candidate is better? Reply with exactly A or B."""


@dataclass(frozen=True)
class TieBreakOutcome:
    """一次 tie-break 的聚合结果."""

    a_wins: int
    b_wins: int
    invalid: int
    preferred: str | None  # "a" / "b" / None（无多数）
    bonus: float  # 有界 search bonus（仅 preferred 多数时 > 0）

    @property
    def total(self) -> int:
        return self.a_wins + self.b_wins + self.invalid


class DiscreteTieBreaker:
    """离散 A/B 集成 tie-breaker.

    Args:
        llm: LLM 网关（偏好调用以 ``agent_role="tiebreaker"`` 记账）
        model: 偏好模型名（空串回退网关默认）
        tolerance: 分数差 ≤ 该值视为打平
        repetitions: A/B 比较次数 K（奇偶交换位置）
        bonus_cap: search bonus 上界（有界，默认对齐 verifier 0.01）
        code_limit: 注入比较提示的代码字符上限（防止输入 token 失控）
    """

    def __init__(
        self,
        llm: LLMGateway,
        *,
        model: str = "",
        tolerance: float = 0.01,
        repetitions: int = 3,
        bonus_cap: float = 0.01,
        code_limit: int = 2000,
    ) -> None:
        if repetitions < 1:
            raise ValueError("tie-breaker repetitions must be positive")
        if not 0.0 <= tolerance < 1.0:
            raise ValueError("tie-breaker tolerance must be in [0, 1)")
        if not 0.0 <= bonus_cap <= 1.0:
            raise ValueError("tie-breaker bonus_cap must be in [0, 1]")
        self._llm = llm
        self._model = model
        self._tolerance = tolerance
        self._repetitions = repetitions
        self._bonus_cap = bonus_cap
        self._code_limit = code_limit

    def is_tie(self, score_a: float, score_b: float) -> bool:
        """任务分数打平判定（或 CI 重叠由调用方折算进 tolerance）."""
        return abs(score_a - score_b) <= self._tolerance

    def break_tie(
        self,
        *,
        task: str,
        code_a: str,
        code_b: str,
        score_a: float,
        score_b: float,
        experiment_id: str | None = None,
    ) -> TieBreakOutcome:
        """执行 K 次 A/B 比较并聚合多数偏好.

        奇数次 a 在前、偶数次 b 在前，抵消位置偏差；无法解析的响应计为
        invalid（不投给任一方）。
        """
        a_wins = 0
        b_wins = 0
        invalid = 0
        for index in range(self._repetitions):
            a_first = index % 2 == 0
            winner = self._compare_once(
                task=task,
                code_a=code_a,
                code_b=code_b,
                score_a=score_a,
                score_b=score_b,
                a_first=a_first,
                experiment_id=experiment_id,
            )
            if winner == "a":
                a_wins += 1
            elif winner == "b":
                b_wins += 1
            else:
                invalid += 1

        total = a_wins + b_wins
        preferred: str | None
        if a_wins > b_wins and a_wins > total / 2:
            preferred = "a"
        elif b_wins > a_wins and b_wins > total / 2:
            preferred = "b"
        else:
            preferred = None
        # 有界 bonus：仅多数偏好时按胜率比例发放（≤ bonus_cap）
        wins = max(a_wins, b_wins) if preferred is not None else 0
        bonus = self._bonus_cap * (wins / total) if preferred is not None and total > 0 else 0.0
        return TieBreakOutcome(
            a_wins=a_wins,
            b_wins=b_wins,
            invalid=invalid,
            preferred=preferred,
            bonus=bonus,
        )

    def _compare_once(
        self,
        *,
        task: str,
        code_a: str,
        code_b: str,
        score_a: float,
        score_b: float,
        a_first: bool,
        experiment_id: str | None,
    ) -> str | None:
        """单次 A/B 比较；返回 "a"/"b"/None（无法解析）."""
        # 位置交换：a_first=False 时提示中 A/B 标签互换，投票按标签回映射
        first_code, second_code = (code_a, code_b) if a_first else (code_b, code_a)
        first_score, second_score = (score_a, score_b) if a_first else (score_b, score_a)
        user_message = TIEBREAK_USER_TEMPLATE.format(
            task=task,
            code_a=first_code[: self._code_limit],
            code_b=second_code[: self._code_limit],
            score_a=first_score,
            score_b=second_score,
        )
        try:
            response = self._llm.chat(
                [
                    {"role": "system", "content": TIEBREAK_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                model=self._model or None,
                temperature=0.0,
                experiment_id=experiment_id,
                agent_role="tiebreaker",
            )
        except Exception:
            logger.debug("Tie-break comparison failed, counting as invalid", exc_info=True)
            return None
        verdict = self._parse_verdict(response.content)
        if verdict is None:
            return None
        # 标签回映射：b 在前时 "A" 实指 code_b
        return verdict if a_first else ("a" if verdict == "b" else "b")

    @staticmethod
    def _parse_verdict(content: str) -> str | None:
        """解析响应裁决：仅接受第一个非空白 token（去尾部标点）恰为 A 或 B.

        避免任意文本误匹配（如 "BOTH are similar" 不应判为 B）；
        常见 LLM 输出 "A"、"A."、"A\n..." 均能解析。
        """
        first_token = content.strip().split(None, 1)[0] if content.strip() else ""
        clean = first_token.rstrip(".,;:!?")
        upper = clean.upper()
        if upper in ("A", "B"):
            return upper.lower()
        return None
