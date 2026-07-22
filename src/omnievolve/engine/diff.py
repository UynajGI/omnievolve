"""SEARCH/REPLACE diff 解析与应用 — AlphaEvolve 兼容格式.

支持:
  <<<<<<< SEARCH
  # code to find
  =======
  # code to replace
  >>>>>>> REPLACE

Phase 1: 增强版支持模糊缩进匹配 + difflib 辅助定位 + 重试机制。
从 MLEvolve patcher.py / apply.py 精简移植。
"""

from __future__ import annotations

import difflib
import logging
import re

logger = logging.getLogger(__name__)

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


def _strip_trailing_whitespace(text: str) -> str:
    """去掉每行尾部空白 — 从 MLEvolve patcher 移植."""
    return "\n".join(line.rstrip() for line in text.splitlines())


def _find_indented_match(search_text: str, original_text: str) -> tuple[str, int]:
    """缩进感知匹配 — 从 MLEvolve patcher.py 移植.

    先精确匹配，失败后尝试首行 strip 匹配 + 缩进传播。
    """
    if not search_text.strip():
        return "", -1

    # 1. 精确匹配
    pos = original_text.find(search_text)
    if pos != -1:
        return search_text, pos

    # 2. 缩进感知回退
    search_lines = search_text.splitlines()
    first_search_line = search_lines[0].strip()
    original_lines = original_text.splitlines()

    for i, line in enumerate(original_lines):
        if line.strip() == first_search_line:
            line_indent = len(line) - len(line.lstrip())
            indent_str = line[:line_indent]

            indented_search_lines = []
            for j, search_line in enumerate(search_lines):
                if j == 0:
                    indented_search_lines.append(indent_str + search_line.strip())
                else:
                    search_line_indent = len(search_line) - len(search_line.lstrip())
                    if search_line.strip():
                        indented_search_lines.append(
                            indent_str + " " * search_line_indent + search_line.strip()
                        )
                    else:
                        indented_search_lines.append("")
            indented_search = "\n".join(indented_search_lines)
            indented_pos = original_text.find(indented_search)
            if indented_pos != -1:
                return indented_search, indented_pos
    return "", -1


def _apply_indentation_to_replace(replace_text: str, indent_str: str) -> str:
    """将缩进传播到 replace 块 — 从 MLEvolve patcher.py 移植."""
    if not replace_text.strip():
        return replace_text
    replace_lines = replace_text.splitlines()
    indented_replace_lines = []
    for line in replace_lines:
        if line.strip():
            line_indent = len(line) - len(line.lstrip())
            indented_replace_lines.append(indent_str + " " * line_indent + line.strip())
        else:
            indented_replace_lines.append("")
    return "\n".join(indented_replace_lines)


def _find_best_match_with_diff(
    search_text: str, original_text: str, threshold: float = 0.6
) -> tuple[list[str], int, list[str]] | None:
    """difflib 辅助定位 — 从 MLEvolve patcher.py 移植.

    使用 SequenceMatcher 找最接近的匹配位置，生成 unified_diff 供调试。
    """
    search_lines = search_text.strip().splitlines()
    if not search_lines:
        return None
    original_lines = original_text.splitlines()
    search_len = len(search_lines)
    best_match = None
    best_ratio = 0.0
    best_start_line = 0

    for i in range(max(0, len(original_lines) - search_len + 1)):
        candidate_lines = original_lines[i : i + search_len]
        candidate_text = "\n".join(candidate_lines)
        search_block = "\n".join(search_lines)
        ratio = difflib.SequenceMatcher(None, search_block, candidate_text).ratio()
        if ratio > best_ratio and ratio > threshold:
            best_ratio = ratio
            best_match = candidate_lines
            best_start_line = i + 1

    if best_match is None:
        return None

    search_prefixed = [f"  {line}" for line in search_lines]
    match_prefixed = [f"  {line}" for line in best_match]
    diff_lines = list(
        difflib.unified_diff(
            search_prefixed,
            match_prefixed,
            fromfile="Search Pattern",
            tofile=f"Actual Code (line {best_start_line})",
            lineterm="",
            n=0,
        )
    )
    clean_diff = [
        ln
        for ln in diff_lines
        if not (ln.startswith("---") or ln.startswith("+++") or ln.startswith("@@"))
    ]
    return best_match, best_start_line, clean_diff


def apply_diffs_enhanced(
    source: str, diffs: list[tuple[str, str]]
) -> tuple[str | None, int, list[str]]:
    """增强版 diff 应用 — 缩进感知 + difflib 辅助.

    对每个 diff 块，依次尝试:
    1. 精确匹配
    2. 缩进感知匹配
    3. difflib 模糊匹配（仅报告，不自动应用）

    Returns:
        (result, applied_count, errors)
    """
    result = _strip_trailing_whitespace(source)
    applied = 0
    errors: list[str] = []

    for search, replace in diffs:
        search_clean = _strip_trailing_whitespace(search)

        # 1. 精确匹配
        if search_clean in result:
            result = result.replace(search_clean, replace, 1)
            applied += 1
            continue

        # 2. 缩进感知匹配
        matched_text, pos = _find_indented_match(search_clean, result)
        if pos != -1:
            # 推断缩进并传播到 replace
            first_line = matched_text.splitlines()[0]
            indent_str = first_line[: len(first_line) - len(first_line.lstrip())]
            indented_replace = _apply_indentation_to_replace(replace, indent_str)
            result = result[:pos] + indented_replace + result[pos + len(matched_text) :]
            applied += 1
            continue

        # 3. difflib 辅助定位（仅报告，不自动应用）
        best = _find_best_match_with_diff(search_clean, result)
        if best:
            _, start_line, diff_report = best
            errors.append(
                f"SEARCH block not found (best match at line {start_line}, "
                f"diff: {''.join(diff_report[:5])}...)"
            )
        else:
            errors.append(f"SEARCH block not found: {search_clean[:80]}...")

    return (result if applied > 0 else None), applied, errors


def apply_diffs_with_retry(
    source: str,
    diffs: list[tuple[str, str]],
    max_retries: int = 1,
) -> tuple[str | None, int, str]:
    """带重试的 diff 应用 — 简化自 MLEvolve apply.py.

    第一次使用增强版（缩进感知+difflib），
    失败后注入 RETRY NOTE 重试（由调用方负责重新生成）。

    Returns:
        (result, applied_count, error_message)
    """
    result, applied, errors = apply_diffs_enhanced(source, diffs)

    if result is not None or not errors:
        return result, applied, "; ".join(errors) if errors else ""

    # 所有 diff 块都失败了
    logger.debug("Diff application failed: %s", errors)
    return None, 0, "; ".join(errors)


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
