from __future__ import annotations

import math
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import xc2f


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "c"

REPRESENTATIVE_EXAMPLES = [
    "001_hello_world.c",
    "002_integer_arithmetic.c",
    "005_if_else.c",
    "007_for_loop.c",
    "011_switch_statement.c",
    "013_simple_function.c",
    "018_recursion_fibonacci.c",
    "019_one_dimensional_array.c",
    "022_two_dimensional_array.c",
    "026_swap_with_pointers.c",
    "034_struct.c",
    "061_complex_numbers.c",
    "094_escape_sequences.c",
    "097_return_struct.c",
    "100_state_machine.c",
]

ADAPTED_FIXTURES = [
    FIXTURE_DIR / "arrays.c",
    FIXTURE_DIR / "complex_numbers.c",
    FIXTURE_DIR / "control_flow.c",
    FIXTURE_DIR / "escape_sequences.c",
    FIXTURE_DIR / "integer_arithmetic.c",
    FIXTURE_DIR / "pointers.c",
    FIXTURE_DIR / "recursion.c",
    FIXTURE_DIR / "return_struct.c",
    FIXTURE_DIR / "state_machine.c",
    FIXTURE_DIR / "two_dimensional_array.c",
]


@pytest.mark.corpus
@pytest.mark.parametrize("filename", REPRESENTATIVE_EXAMPLES)
def test_representative_example_transpiles(filename: str) -> None:
    source = (PROJECT_ROOT / filename).read_text(encoding="utf-8")

    fortran = xc2f.transpile_c_to_fortran(source)

    assert fortran.strip()
    assert "program main" in fortran.lower()


def assert_semantically_equal_output(c_output: str, fortran_output: str) -> None:
    c_tokens = c_output.split()
    fortran_tokens = fortran_output.split()
    assert len(fortran_tokens) == len(c_tokens)
    for c_token, fortran_token in zip(c_tokens, fortran_tokens):
        try:
            c_number = float(c_token)
            fortran_number = float(fortran_token)
        except ValueError:
            assert fortran_token == c_token
        else:
            assert math.isclose(fortran_number, c_number, rel_tol=1e-6, abs_tol=1e-9)


@pytest.mark.integration
@pytest.mark.corpus
@pytest.mark.skipif(
    shutil.which("gcc") is None or shutil.which("gfortran") is None,
    reason="gcc and gfortran are required",
)
@pytest.mark.parametrize("c_path", ADAPTED_FIXTURES, ids=lambda p: p.stem)
def test_adapted_c_fixture_matches_generated_fortran(c_path: Path, tmp_path: Path) -> None:
    c_executable = tmp_path / "original.exe"
    fortran_source = tmp_path / "transformed.f90"
    fortran_executable = tmp_path / "transformed.exe"

    subprocess.run(
        ["gcc", str(c_path), "-lm", "-o", str(c_executable)],
        check=True,
        capture_output=True,
        text=True,
    )
    transpile = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "xc2f.py"), str(c_path), "--out", str(fortran_source)],
        capture_output=True,
        text=True,
    )
    assert transpile.returncode == 0, transpile.stdout + transpile.stderr
    subprocess.run(
        ["gfortran", str(fortran_source), "-o", str(fortran_executable)],
        check=True,
        capture_output=True,
        text=True,
    )

    c_run = subprocess.run([str(c_executable)], check=True, capture_output=True, text=True)
    fortran_run = subprocess.run([str(fortran_executable)], check=True, capture_output=True, text=True)

    assert_semantically_equal_output(c_run.stdout, fortran_run.stdout)
