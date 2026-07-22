"""Shared prompt fragments — 通用 prompt 模板.

从 MLEvolve agents/prompts/shared.py 移植。
提供可复用的 prompt 片段，供 Coder/Critic/Debug 共用。
"""

from __future__ import annotations

ROBUSTNESS_GENERALIZATION_STRATEGY = {
    "Robustness & Generalization Strategy": [
        "**To improve model robustness and generalization on unseen data:**",
        "- Architecture: Match model inductive bias to data structure",
        "- Regularization: Consider Dropout, Batch/Layer Norm, Weight Decay",
        "- Learning Rate: Consider Cosine Annealing or ReduceLROnPlateau",
        "- Validation: Monitor validation metrics and use early stopping",
        "- Data Augmentation: Apply domain-appropriate transformations",
        "- Ensemble: Consider averaging predictions from multiple runs",
    ]
}


def prompt_leakage_prevention() -> dict:
    """Data leakage prevention prompt."""
    return {
        "Data Leakage Prevention": [
            "- NEVER use test/validation data during training",
            "- Ensure proper train/validation/test splits BEFORE feature engineering",
            "- Compute statistics (mean, std, min, max) ONLY on training data",
            "- Do not peek at test labels or submission format for model selection",
            "- Cross-validation: use proper fold assignments, no data from other folds",
        ]
    }


def prompt_resp_fmt() -> dict:
    """Response format instructions."""
    return {
        "Response Format": [
            "Provide your solution as complete Python code in a single code block.",
            "Include all necessary imports at the top.",
            "The code should be directly runnable without modification.",
            "Add brief comments explaining non-obvious design choices.",
        ]
    }


def format_prompt_section(d: dict) -> str:
    """将 prompt dict 格式化为可注入 system prompt 的文本."""
    parts: list[str] = []
    for title, items in d.items():
        parts.append(f"\n## {title}")
        for item in items:
            parts.append(f"  {item}")
    return "\n".join(parts)
