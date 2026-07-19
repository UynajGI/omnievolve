"""Prompt 变异器.

S9: Prompt 基因变异（L1 级别，需要 Replay）
"""

from __future__ import annotations

import logging
import random

logger = logging.getLogger(__name__)


class PromptEvolver:
    """Prompt 基因变异器."""

    # 变异操作
    MUTATIONS = [
        "add_constraint",
        "add_example",
        "rephrase",
        "add_step",
        "remove_redundancy",
        "change_tone",
    ]

    def __init__(
        self,
        *,
        mutation_rate: float = 0.2,
        max_mutations: int = 2,
    ) -> None:
        self._mutation_rate = mutation_rate
        self._max_mutations = max_mutations

    def evolve(
        self,
        prompt: str,
        *,
        feedback: str | None = None,
    ) -> tuple[str, list[str]]:
        """变异 prompt.

        Returns:
            (new_prompt, applied_mutations)
        """
        if random.random() > self._mutation_rate:
            return prompt, []

        mutations_applied = []
        new_prompt = prompt

        num_mutations = random.randint(1, self._max_mutations)
        selected = random.sample(self.MUTATIONS, min(num_mutations, len(self.MUTATIONS)))

        for mutation in selected:
            new_prompt = self._apply_mutation(new_prompt, mutation, feedback)
            mutations_applied.append(mutation)

        return new_prompt, mutations_applied

    def _apply_mutation(
        self,
        prompt: str,
        mutation: str,
        feedback: str | None,
    ) -> str:
        """应用单个变异."""
        if mutation == "add_constraint":
            constraints = [
                "\n\nAdditional constraint: Ensure the solution is efficient.",
                "\n\nAdditional constraint: Handle edge cases properly.",
                "\n\nAdditional constraint: Prioritize correctness over speed.",
            ]
            return prompt + random.choice(constraints)

        elif mutation == "add_example":
            return prompt + "\n\nExample: Input -> Expected Output"

        elif mutation == "rephrase":
            # 简化：在末尾添加强调
            return prompt + "\n\nImportant: Focus on the key requirements above."

        elif mutation == "add_step":
            steps = [
                "\n\nStep 1: Analyze the problem.\nStep 2: Design solution.\nStep 3: Implement.",
                "\n\nProcess: Think -> Plan -> Code -> Verify.",
            ]
            return prompt + random.choice(steps)

        elif mutation == "remove_redundancy":
            # 移除重复的空行
            lines = prompt.split("\n")
            unique_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped or not unique_lines or unique_lines[-1].strip():
                    unique_lines.append(line)
            return "\n".join(unique_lines)

        elif mutation == "change_tone":
            return prompt.replace("You are", "Act as").replace("Your role", "Your mission")

        return prompt
