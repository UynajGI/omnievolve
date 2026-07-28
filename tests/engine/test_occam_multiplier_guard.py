from omnievolve.engine.fast_loop import (
    _align_occam_candidate_scope,
    _occam_thought_targets,
    _protect_occam_multiplier,
)


def test_occam_multiplier_guard_restores_only_audited_kernel():
    parent = '''"""OCCAM_PROTECTED_MULTIPLIER"""
class Netlist:
    pass

def read_train(path):
    return path

def detect(value):
    return value

def xvar(i):
    return i

def yvar(i):
    return i

def _add_bits(a, b):
    return a + b

def _multiply_bits(a, b):
    return a * b

def build_multiplier(a, b):
    return _multiply_bits(a, b)

def _square_bits(a):
    return a * a

def build_sum_of_squares(a, b):
    return a * a + b * b

def run():
    return build_multiplier(1, 1)
'''
    candidate = parent.replace("return a * b", "return 0").replace(
        "return a * a + b * b", "return 42"
    )

    protected = _protect_occam_multiplier(parent, candidate, "OCCAM_PROTECTED_MULTIPLIER")

    assert "def _multiply_bits(a, b):\n    return a * b" in protected
    assert "def build_sum_of_squares(a, b):\n    return a * a + b * b" in protected


def test_occam_multiplier_guard_reassembles_incomplete_rewrite():
    parent = '''"""OCCAM_PROTECTED_MULTIPLIER"""
class Netlist:
    pass

def read_train(path):
    return path

def detect(value):
    return value

def xvar(i):
    return i

def yvar(i):
    return i

def _add_bits(a, b):
    return a + b

def _multiply_bits(a, b):
    return a * b

def build_multiplier(a, b):
    return _multiply_bits(a, b)

def _square_bits(a):
    return a * a

def build_sum_of_squares(a, b):
    return a * a + b * b

def build_adder(a, b):
    return a + b

def build_absdiff(a, b):
    return abs(a - b)

def run():
    return build_multiplier(1, 1)
'''
    incomplete = '''def build_adder(a, b):
    return b + a
'''

    protected = _protect_occam_multiplier(parent, incomplete, "OCCAM_PROTECTED_MULTIPLIER")

    assert "class Netlist:" in protected
    assert "def _multiply_bits(a, b):\n    return a * b" in protected
    assert "def build_adder(a, b):\n    return b + a" in protected


def test_occam_thought_targets_uses_fenced_json_thought_only():
    thought = '''```json
{"thought":"Apply Booth encoding to Mystery C's multiplier.",
 "risk_notes":"Do not damage Mystery D's squarer."}
```'''

    assert _occam_thought_targets(thought) == {"C"}


def test_occam_scope_restores_d_when_thought_targets_c():
    parent = '''"""#71 Occam's Circuit"""
def _add_bits(a, b):
    return a + b

def _multiply_bits(a, b):
    return a * b

def build_multiplier(a, b):
    return _multiply_bits(a, b)

def _square_bits(a):
    return a * a

def build_sum_of_squares(a, b):
    return _square_bits(a) + _square_bits(b)
'''
    candidate = parent.replace("return a * a", "return 0")

    aligned, reverted = _align_occam_candidate_scope(
        parent,
        candidate,
        "Apply Booth encoding to Mystery C's multiplier.",
        "#71 Occam's Circuit",
    )

    assert "_square_bits" in reverted
    assert "def _square_bits(a):\n    return a * a" in aligned
