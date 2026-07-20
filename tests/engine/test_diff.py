"""SEARCH/REPLACE diff 解析与应用测试 — AlphaEvolve 兼容格式."""

from __future__ import annotations

from omnievolve.engine.diff import (
    apply_diffs,
    extract_parent_code,
    parse_diffs,
    parse_evolve_blocks,
)


class TestParseDiffs:
    def test_single_block(self):
        text = """Here's my change:
<<<<<<< SEARCH
old_line = 1
=======
new_line = 2
>>>>>>> REPLACE
"""
        diffs = parse_diffs(text)
        assert len(diffs) == 1
        assert diffs[0] == ("old_line = 1", "new_line = 2")

    def test_multiple_blocks(self):
        text = """<<<<<<< SEARCH
a = 1
=======
a = 2
>>>>>>> REPLACE

Some explanation.

<<<<<<< SEARCH
b = 3
=======
b = 4
>>>>>>> REPLACE
"""
        diffs = parse_diffs(text)
        assert len(diffs) == 2
        assert diffs[0] == ("a = 1", "a = 2")
        assert diffs[1] == ("b = 3", "b = 4")

    def test_no_blocks(self):
        text = "Just regular text without any diffs."
        diffs = parse_diffs(text)
        assert diffs == []

    def test_multiline_search_replace(self):
        text = """<<<<<<< SEARCH
def foo():
    return 1
=======
def foo():
    return 2
>>>>>>> REPLACE
"""
        diffs = parse_diffs(text)
        assert len(diffs) == 1
        assert "return 1" in diffs[0][0]
        assert "return 2" in diffs[0][1]

    def test_trailing_whitespace_stripped(self):
        text = """<<<<<<< SEARCH
x = 1   \n=======\ny = 2   \n>>>>>>> REPLACE
"""
        diffs = parse_diffs(text)
        assert diffs[0] == ("x = 1", "y = 2")

    def test_empty_replace_block(self):
        text = """<<<<<<< SEARCH
to_delete = True
=======
>>>>>>> REPLACE
"""
        diffs = parse_diffs(text)
        assert len(diffs) == 1
        assert diffs[0] == ("to_delete = True", "")

    def test_code_after_markers_included(self):
        """Ensure code containing '<' or '>' chars inside blocks works."""
        text = """<<<<<<< SEARCH
x = a < b
=======
x = a > b
>>>>>>> REPLACE
"""
        diffs = parse_diffs(text)
        assert len(diffs) == 1
        assert diffs[0] == ("x = a < b", "x = a > b")


class TestApplyDiffs:
    def test_simple_replacement(self):
        source = "x = 1\ny = 2"
        diffs = [("x = 1", "x = 42")]
        result = apply_diffs(source, diffs)
        assert result == "x = 42\ny = 2"

    def test_no_match_returns_none(self):
        source = "x = 1"
        diffs = [("nonexistent", "whatever")]
        result = apply_diffs(source, diffs)
        assert result is None

    def test_multiple_diffs_applied_sequentially(self):
        source = "a = 1\nb = 2\nc = 3"
        diffs = [("a = 1", "a = 10"), ("c = 3", "c = 30")]
        result = apply_diffs(source, diffs)
        assert result == "a = 10\nb = 2\nc = 30"

    def test_only_first_match_replaced(self):
        source = "x = 1\nx = 1\nx = 1"
        diffs = [("x = 1", "x = 99")]
        result = apply_diffs(source, diffs)
        assert result == "x = 99\nx = 1\nx = 1"

    def test_empty_diffs_returns_none(self):
        source = "x = 1"
        result = apply_diffs(source, [])
        assert result is None

    def test_multiline_block_replacement(self):
        source = "def foo():\n    return 1\n\nbar = 2"
        diffs = [("def foo():\n    return 1", "def foo():\n    return 2")]
        result = apply_diffs(source, diffs)
        assert "return 2" in result
        assert "return 1" not in result

    def test_second_diff_when_first_fails(self):
        """If first diff doesn't match, second still gets applied."""
        source = "keep = 1\nchange = 2"
        diffs = [("nope", "yes"), ("change = 2", "change = 99")]
        result = apply_diffs(source, diffs)
        assert result == "keep = 1\nchange = 99"

    def test_replace_can_reinsert(self):
        """Replace block can re-add code that was there."""
        source = "x = 1"
        diffs = [("x = 1", "x = 1\ny = 2")]
        result = apply_diffs(source, diffs)
        assert result == "x = 1\ny = 2"


class TestParseEvolveBlocks:
    def test_single_block(self):
        source = """before = 1
# EVOLVE-BLOCK-START
def target():
    return 42
# EVOLVE-BLOCK-END
after = 2
"""
        cleaned, blocks = parse_evolve_blocks(source)
        assert len(blocks) == 1
        start, end, content = blocks[0]
        assert "def target()" in content
        assert "return 42" in content
        # Markers removed from cleaned
        assert "EVOLVE-BLOCK-START" not in cleaned
        assert "EVOLVE-BLOCK-END" not in cleaned
        # Non-block code preserved
        assert "before = 1" in cleaned
        assert "after = 2" in cleaned

    def test_multiple_blocks(self):
        source = """# EVOLVE-BLOCK-START
part_a = 1
# EVOLVE-BLOCK-END
middle = 2
# EVOLVE-BLOCK-START
part_b = 3
# EVOLVE-BLOCK-END
"""
        cleaned, blocks = parse_evolve_blocks(source)
        assert len(blocks) == 2
        assert "part_a = 1" in blocks[0][2]
        assert "part_b = 3" in blocks[1][2]

    def test_no_blocks(self):
        source = "x = 1\ny = 2"
        cleaned, blocks = parse_evolve_blocks(source)
        assert blocks == []
        assert cleaned == source

    def test_unclosed_block(self):
        """Unclosed block — content is not captured as a block."""
        source = """# EVOLVE-BLOCK-START
uncommitted code
"""
        cleaned, blocks = parse_evolve_blocks(source)
        assert blocks == []

    def test_empty_block(self):
        source = """# EVOLVE-BLOCK-START
# EVOLVE-BLOCK-END
"""
        cleaned, blocks = parse_evolve_blocks(source)
        assert len(blocks) == 1
        assert blocks[0][2] == ""


class TestExtractParentCode:
    def test_with_blocks_extracts_only_block_content(self):
        source = """imports here
# EVOLVE-BLOCK-START
def solve():
    return 42
# EVOLVE-BLOCK-END
other = 1
"""
        result = extract_parent_code(source)
        assert "def solve()" in result
        assert "return 42" in result
        assert "imports here" not in result
        assert "other = 1" not in result

    def test_without_blocks_returns_full_source(self):
        source = "x = 1\ny = 2"
        result = extract_parent_code(source)
        assert result == source

    def test_multiple_blocks_joined(self):
        source = """# EVOLVE-BLOCK-START
a = 1
# EVOLVE-BLOCK-END
gap = 2
# EVOLVE-BLOCK-START
b = 3
# EVOLVE-BLOCK-END
"""
        result = extract_parent_code(source)
        assert "a = 1" in result
        assert "b = 3" in result
        assert "gap = 2" not in result

    def test_language_param_accepted(self):
        """The candidate_language param is accepted but doesn't change behavior."""
        source = "x = 1"
        result = extract_parent_code(source, candidate_language="rust")
        assert result == source
