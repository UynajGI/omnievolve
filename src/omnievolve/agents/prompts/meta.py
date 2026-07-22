"""Meta-scratchpad prompt templates.

从 ShinkaEvolve prompts_meta.py 移植。
3 步元推理：个体摘要 → 全局洞察 → 可操作建议。
"""

from __future__ import annotations

# Step 1: Individual Program Summaries
META_STEP1_SYSTEM_MSG = (
    "You are an expert programming assistant analyzing an individual program. "
    "Create a standalone summary focusing on implementation details and "
    "evaluation feedback. Consider how this specific program performs and "
    "what implementation choices were made."
)

META_STEP1_USER_MSG = (
    "# Program to Analyze\n"
    "{individual_program_msg}\n\n"
    "# Instructions\n\n"
    "Create a standalone summary for this program using the following "
    "exact format:\n\n"
    "**Program Name: [Short summary name (up to 10 words)]**\n"
    "- **Implementation**: [Key details (1-2 sentences)]\n"
    "- **Performance**: [Score/metrics summary (1 sentence)]\n"
    "- **Feedback**: [Key insights from evaluation (1-2 sentences)]\n"
)

# Step 2: Global Insights Scratchpad
META_STEP2_SYSTEM_MSG = (
    "You are an expert programming assistant analyzing program "
    "evaluation results to extract actionable optimization insights. Focus "
    "on concrete performance data and implementation details."
)

META_STEP2_USER_MSG = (
    "# Individual Program Summaries\n"
    "{individual_summaries}\n\n"
    "# Previous Global Insights (if any)\n"
    "{previous_insights}\n\n"
    "# Current Best Program\n"
    "{best_program_info}\n\n"
    "# Instructions\n\n"
    "Analyze the program evaluation results to extract concrete insights. "
    "Update or create insights in these sections:\n\n"
    "## Successful Algorithmic Patterns\n"
    "- Specific implementation changes that led to score improvements\n\n"
    "## Ineffective Approaches\n"
    "- What did NOT work and should be avoided\n\n"
    "## New Insights\n"
    "- Novel observations or unexpected patterns\n\n"
    "## Performance Analysis\n"
    "- Which techniques correlated with best/worst performance\n"
)

# Step 3: Actionable Recommendations
META_STEP3_SYSTEM_MSG = (
    "You are an expert programming assistant generating actionable "
    "recommendations for the next generation of code optimization."
)

META_STEP3_USER_MSG = (
    "# Global Insights\n"
    "{insights}\n\n"
    "# Previous Recommendations (if any)\n"
    "{previous_recommendations}\n\n"
    "# Current Best Program\n"
    "{best_program_info}\n\n"
    "# Instructions\n\n"
    "Based on the insights above, generate 3-5 specific, actionable "
    "recommendations for improving the code in the next generation. "
    "Each recommendation should be:\n"
    "1. Concrete and specific (not generic advice)\n"
    "2. Backed by evidence from the insights\n"
    "3. Implementable in a single code change\n\n"
    "Format each as a bullet point starting with '- '."
)
