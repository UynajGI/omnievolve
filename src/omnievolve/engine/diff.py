"""SEARCH/REPLACE diff 解析与应用 — AlphaEvolve 兼容格式.

支持:
  <<<<<<< SEARCH
  # code to find
  =======
  # code to replace
  >>>>>>> REPLACE
"""

from __future__ import annotations

import re

# 匹配 SEARCH/REPLACE 块
_DIFF_PATTERN = re.compile(
    r"<<<<<<< SEARCH\s*\n(.*?)=======\s*\n(.*?)>>>>>>> REPLACE",
    re.DOTALL,
)


def parse_diffs(text: str) -> list[tuple[str, str]]:
    """从 LLM 输出中解析 SEARCH/REPLACE 块.

    Args:
        text: LLM 输出文本

    Returns:
        [(search_block, replace_block), ...] 块列表
    """
    matches = _DIFF_PATTERN.findall(text)
    return [(m[0].rstrip(), m[1].rstrip()) for m in matches]


def apply_diffs(source: str, diffs: list[tuple[str, str]]) -> str | None:
    """将 SEARCH/REPLACE diff 应用到源代码.

    按顺序应用每个 diff 块。如果 SEARCH 块未找到，跳过该块。
    所有 diff 应用完成后返回修改后的代码，如果没有任何 diff 被应用则返回 None。

    Args:
        source: 原始源代码
        diffs: [(search, replace), ...] 块列表

    Returns:
        修改后的代码，或 None（没有 diff 被应用）
    """
    result = source
    applied = 0

    for search, replace in diffs:
        if search in result:
            # 只替换第一个匹配（精确替换）
            result = result.replace(search, replace, 1)
            applied += 1

    return result if applied > 0 else None


def parse_evolve_blocks(source: str) -> tuple[str, list[tuple[int, int, str]]]:
    """查找 EVOLVE-BLOCK-START / EVOLVE-BLOCK-END 标记.

    Args:
        source: 源代码

    Returns:
        (cleaned_source, blocks)
        cleaned_source: 去除了标记的源代码
        blocks: [(start_line, end_line, content), ...] 进化块信息
    """
    EVOLVE_START = "# EVOLVE-BLOCK-START"
    EVOLVE_END = "# EVOLVE-BLOCK-END"

    blocks: list[tuple[int, int, str]] = []
    lines = source.split("\n")
    cleaned: list[str] = []
    in_block = False
    block_lines: list[str] = []
    block_start = 0

    for i, line in enumerate(lines):
        if EVOLVE_START in line:
            in_block = True
            block_start = i
            block_lines = []
            continue
        if EVOLVE_END in line:
            if in_block:
                content = "\n".join(block_lines)
                blocks.append((block_start, i - 1, content))
                in_block = False
                # 将内容（不含标记）加入清理后的代码
                cleaned.append(content)
            continue
        if in_block:
            block_lines.append(line)
        cleaned.append(line)

    return "\n".join(cleaned), blocks


def extract_parent_code(source: str, candidate_language: str = "python") -> str:
    """从源代码中提取可进化的代码.

    如果存在 EVOLVE-BLOCK 标记，只返回标记块的内容。
    否则返回完整源代码。

    Args:
        source: 原始源代码
        candidate_language: 语言标识

    Returns:
        可进化的代码部分
    """
    _, blocks = parse_evolve_blocks(source)
    if blocks:
        return "\n\n".join(b[2] for b in blocks)
    return source
