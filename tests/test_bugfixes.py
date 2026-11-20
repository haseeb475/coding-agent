"""Regression tests for bugs fixed while preparing the public release."""

import pytest

from evaluation.runner import verify_solution
from evaluation.swebench_runner import is_test_path, strip_test_file_changes
from execution.sandbox import parse_pytest_counts, run_pytest


@pytest.mark.parametrize("raw,expected", [
    ("=== 5 passed in 0.12s ===", (5, 0, 0)),
    ("=== 1 failed, 2 passed in 0.3s ===", (2, 1, 0)),
    ("=== 3 passed, 1 failed, 2 errors in 1.0s ===", (3, 1, 2)),
    ("=== 1 error in 0.1s ===", (0, 0, 1)),
    ("test output mentions 9 passed\n=== 1 passed in 0.1s ===", (1, 0, 0)),
    ("no summary here", (0, 0, 0)),
])
def test_parse_pytest_counts(raw, expected):
    assert parse_pytest_counts(raw) == expected


def test_run_pytest_reports_errors(tmp_path):
    (tmp_path / "test_x.py").write_text("import does_not_exist\n\ndef test_a():\n    pass\n")
    out = run_pytest(tmp_path, "test_x.py")
    assert out.startswith("[TEST_RESULT:FAIL]")
    assert "errors=1" in out.splitlines()[0]


def test_verify_solution_recognizes_passing_tests(tmp_path):
    (tmp_path / "solution.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "test_solution.py").write_text(
        "from solution import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    assert verify_solution(tmp_path) is True
    # Different length so Python's mtime+size bytecode check sees the change.
    (tmp_path / "solution.py").write_text("def add(a, b):\n    return a - b - 100\n")
    assert verify_solution(tmp_path) is False


@pytest.mark.parametrize("path,is_test", [
    ("astropy/modeling/tests/test_separable.py", True),
    ("tests/foo.py", True),
    ("pkg/test_utils.py", True),
    ("pkg/thing_test.py", True),
    ("pkg/latest_test_results.py", False),
    ("src/contest_utils.py", False),
    ("astropy/modeling/separable.py", False),
])
def test_is_test_path(path, is_test):
    assert is_test_path(path) is is_test


def test_strip_test_file_changes_keeps_source_files():
    patch = (
        "diff --git a/pkg/latest_x.py b/pkg/latest_x.py\n+fix\n"
        "diff --git a/pkg/tests/test_x.py b/pkg/tests/test_x.py\n+test change\n"
        "diff --git a/pkg/core.py b/pkg/core.py\n+fix2"
    )
    cleaned, stripped = strip_test_file_changes(patch)
    assert stripped == ["pkg/tests/test_x.py"]
    assert "latest_x.py" in cleaned and "core.py" in cleaned
    assert "test change" not in cleaned
    assert strip_test_file_changes("") == ("", [])
