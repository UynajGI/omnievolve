"""Response 解析工具 — LLM 输出提取.

从 MLEvolve agents/utils/response.py 精简移植（去掉 black 依赖）。
集中管理 LLM 输出的正则提取逻辑，避免各 Agent 重复实现。
"""

from __future__ import annotations

import json
import re


def wrap_code(code: str, lang: str = "python") -> str:
    """代码块包装."""
    return f"```{lang}\n{code}\n```"


def is_valid_python_script(script: str) -> bool:
    """检查是否为合法 Python 脚本."""
    try:
        compile(script, "<string>", "exec")
        return True
    except SyntaxError:
        return False


def extract_code(text: str) -> str:
    """从 LLM 输出提取 python 代码块.

    优先提取 ```python ... ``` 块，失败则尝试裸代码。
    """
    parsed_codes: list[str] = []

    matches = re.findall(r"```(python)?\n*(.*?)\n*```", text, re.DOTALL)
    for match in matches:
        code_block = match[1]
        parsed_codes.append(code_block)

    if not parsed_codes:
        matches = re.findall(r"^(```(python)?)?\n?(.*?)\n?(```)?$", text, re.DOTALL)
        if matches:
            code_block = matches[0][2]
            parsed_codes.append(code_block)

    valid_code_blocks = [c for c in parsed_codes if is_valid_python_script(c)]
    return "\n\n".join(valid_code_blocks)


def extract_jsons(text: str) -> list[dict]:
    """从文本提取 JSON 对象."""
    json_objects: list[dict] = []
    matches = re.findall(r"\{.*?\}", text, re.DOTALL)
    for match in matches:
        try:
            json_obj = json.loads(match)
            json_objects.append(json_obj)
        except json.JSONDecodeError:
            pass

    if not json_objects and not text.endswith("}"):
        json_objects = extract_jsons(text + "}")
        if json_objects:
            return json_objects

    return json_objects


def extract_review(text: str) -> dict:
    """从 LLM 输出提取 JSON 审查结果.

    优先提取 ```json ... ``` 块，失败则尝试 extract_jsons。
    """
    parsed_codes: list[str] = []

    matches = re.findall(r"```(json)?\n*(.*?)\n*```", text, re.DOTALL)
    for match in matches:
        code_block = match[1]
        parsed_codes.append(code_block)

    if not parsed_codes:
        matches = re.findall(r"^(```(json)?)?\n?(.*?)\n?(```)?$", text, re.DOTALL)
        if matches:
            code_block = matches[0][2]
            parsed_codes.append(code_block)

    if not parsed_codes or not parsed_codes[0].strip():
        json_objects = extract_jsons(text)
        if json_objects:
            return json_objects[0]
        raise ValueError("No JSON found in text")

    try:
        return json.loads(parsed_codes[0].strip())
    except json.JSONDecodeError:
        json_objects = extract_jsons(text)
        if json_objects:
            return json_objects[0]
        raise


def extract_text_up_to_code(s: str) -> str:
    """提取代码块之前的文本."""
    if "```" not in s:
        return ""
    return s[: s.find("```")].strip()


def extract_plan_from_diff_response(text: str) -> str:
    """从 diff 响应中提取计划文本."""
    if not text:
        return ""

    stop_tokens = [
        "<<<<<<< SEARCH",
        "< SEARCH",
        ">>>>>>> REPLACE",
        "=======",
        "```",
    ]

    def cut_at_stop(s: str) -> str:
        indices = [s.find(token) for token in stop_tokens if s.find(token) != -1]
        if indices:
            return s[: min(indices)]
        return s

    if "Fixed Code Plan:" in text:
        candidate = text.split("Fixed Code Plan:", 1)[1]
        return cut_at_stop(candidate).strip()

    if "Plan:" in text:
        candidate = text.split("Plan:", 1)[1]
        return cut_at_stop(candidate).strip()

    return cut_at_stop(text).strip()


def trim_long_string(string: str, threshold: int = 5100, k: int = 2500) -> str:
    """截断长字符串，保留首尾关键信息.

    当字符串超过 threshold 时，保留前 k 和后 k 字符。
    如果中间有关键验证行（如 "Final Validation ... : <num>"），会保留到中间。
    """
    if len(string) <= threshold:
        return string

    strict = re.compile(
        r"^Final\s+Validation\s+\w+\s*[:=]\s*[-+]?\d",
        re.IGNORECASE | re.MULTILINE,
    )
    key_lines = [line for line in string.split("\n") if strict.search(line)]
    if not key_lines:
        loose = re.compile(
            r"Final\s+[\w\s]*?Validation\s+[\w\s]*?[:=]\s*[-+]?\d",
            re.IGNORECASE,
        )
        key_lines = [line for line in string.split("\n") if loose.search(line)]

    first_k_chars = string[:k]
    last_k_chars = string[-k:]
    truncated_len = len(string) - 2 * k

    if key_lines:
        key_block = "\n".join(key_lines[-3:])
        return (
            f"{first_k_chars}\n"
            f" ... [{truncated_len} characters truncated] ... \n"
            f"{key_block}\n"
            f" ... [output continues] ... \n"
            f"{last_k_chars}"
        )
    return f"{first_k_chars}\n ... [{truncated_len} characters truncated] ... \n{last_k_chars}"
