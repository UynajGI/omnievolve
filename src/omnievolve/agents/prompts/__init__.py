"""结构化 Prompt 目录.

从 ShinkaEvolve prompts/ 移植，按功能组织 prompt 模板。
导入路径兼容旧 `from omnievolve.agents.prompts import ...`。
"""

from omnievolve.agents.prompts.base import (
    ROBUSTNESS_GENERALIZATION_STRATEGY,
    format_prompt_section,
    prompt_leakage_prevention,
    prompt_resp_fmt,
)
from omnievolve.agents.prompts.fix import (
    FIX_ITER_MSG,
    FIX_SYS_FORMAT,
    format_error_output_section,
)
from omnievolve.agents.prompts.meta import (
    META_STEP1_SYSTEM_MSG,
    META_STEP1_USER_MSG,
    META_STEP2_SYSTEM_MSG,
    META_STEP2_USER_MSG,
    META_STEP3_SYSTEM_MSG,
    META_STEP3_USER_MSG,
)

__all__ = [
    # base
    "ROBUSTNESS_GENERALIZATION_STRATEGY",
    "format_prompt_section",
    "prompt_leakage_prevention",
    "prompt_resp_fmt",
    # fix
    "FIX_SYS_FORMAT",
    "FIX_ITER_MSG",
    "format_error_output_section",
    # meta
    "META_STEP1_SYSTEM_MSG",
    "META_STEP1_USER_MSG",
    "META_STEP2_SYSTEM_MSG",
    "META_STEP2_USER_MSG",
    "META_STEP3_SYSTEM_MSG",
    "META_STEP3_USER_MSG",
]
