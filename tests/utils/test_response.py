"""Response 解析工具测试."""

from omnievolve.utils.response import (
    extract_code,
    extract_jsons,
    extract_plan_from_diff_response,
    extract_review,
    is_valid_python_script,
    trim_long_string,
    wrap_code,
)


class TestWrapCode:
    def test_wrap_python(self):
        result = wrap_code("print('hello')")
        assert result == "```python\nprint('hello')\n```"

    def test_wrap_custom_lang(self):
        result = wrap_code("SELECT 1", lang="sql")
        assert "sql" in result


class TestExtractCode:
    def test_extract_from_markdown(self):
        text = "Here is code:\n```python\ndef foo():\n    return 1\n```\nDone."
        result = extract_code(text)
        assert "def foo():" in result

    def test_extract_empty(self):
        assert extract_code("no code here") == ""


class TestExtractJsons:
    def test_single_json(self):
        text = 'Result: {"passed": true, "feedback": "ok"}'
        result = extract_jsons(text)
        assert len(result) == 1
        assert result[0]["passed"] is True

    def test_no_json(self):
        assert extract_jsons("no json here") == []


class TestTrimLongString:
    def test_short_string_unchanged(self):
        s = "short"
        assert trim_long_string(s) == s

    def test_long_string_truncated(self):
        s = "x" * 10000
        result = trim_long_string(s)
        assert len(result) < len(s)
        assert "truncated" in result

    def test_key_lines_preserved(self):
        s = "header\n" + "x" * 10000 + "\nFinal Validation Accuracy: 0.95\nfooter"
        result = trim_long_string(s)
        assert "Final Validation Accuracy: 0.95" in result


class TestIsValidPythonScript:
    def test_valid(self):
        assert is_valid_python_script("def foo():\n    return 1") is True

    def test_invalid(self):
        assert is_valid_python_script("def foo(") is False


class TestExtractPlanFromDiffResponse:
    def test_with_plan(self):
        text = "Plan: Sort the array using quicksort\n<<<<<<< SEARCH"
        result = extract_plan_from_diff_response(text)
        assert "quicksort" in result

    def test_empty(self):
        assert extract_plan_from_diff_response("") == ""


class TestExtractReview:
    def test_json_block(self):
        text = '```json\n{"passed": true, "feedback": "good"}\n```'
        result = extract_review(text)
        assert result["passed"] is True
