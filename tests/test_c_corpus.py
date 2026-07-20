from __future__ import annotations

import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import xc2f


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = Path(__file__).parent / "corpus"
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

NEWLY_SUPPORTED_EXAMPLES = [
    "015_void_function.c",
    "029_calloc_realloc.c",
    "031_string_functions.c",
    "039_union.c",
    "052_function_pointer.c",
    "053_array_of_function_pointers.c",
    "054_pointer_to_pointer.c",
    "062_goto_statement.c",
    "074_linked_list.c",
    "075_recursive_struct.c",
    "080_qsort.c",
    "081_memcpy_memset.c",
    "082_unsigned_overflow.c",
    "083_short_circuit_evaluation.c",
    "090_generic_selection.c",
    "096_nested_ternary.c",
]

ERRORS4_NUMERICAL_EXAMPLES = [
    "03_min_max.c",
    "06_vector_norm.c",
    "07_linspace.c",
    "08_polynomial_horner.c",
    "09_centered_derivative.c",
    "10_trapezoidal_integration.c",
    "11_simpson_integration.c",
    "12_bisection.c",
    "13_newton.c",
    "14_gaussian_elimination.c",
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
    source = (CORPUS_DIR / filename).read_text(encoding="utf-8")

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


def compile_transpile_and_run(
    c_path: Path,
    tmp_path: Path,
    *,
    run_args: list[str] | None = None,
) -> tuple[subprocess.CompletedProcess[bytes], subprocess.CompletedProcess[bytes]]:
    c_dir = tmp_path / "c"
    fortran_dir = tmp_path / "fortran"
    c_dir.mkdir(parents=True)
    fortran_dir.mkdir(parents=True)
    c_executable = c_dir / "program.exe"
    fortran_source = fortran_dir / "program.f90"
    fortran_executable = fortran_dir / "program.exe"

    subprocess.run(
        ["gcc", str(c_path), "-lm", "-o", str(c_executable)],
        cwd=c_dir,
        check=True,
        capture_output=True,
    )
    transpile = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "xc2f.py"), str(c_path), "--out", str(fortran_source)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert transpile.returncode == 0, transpile.stdout + transpile.stderr
    subprocess.run(
        ["gfortran", str(fortran_source), *xc2f.DEFAULT_GFORTRAN_FLAGS, "-o", str(fortran_executable)],
        cwd=fortran_dir,
        check=True,
        capture_output=True,
    )

    arguments = run_args or []
    c_run = subprocess.run(
        [str(c_executable), *arguments],
        cwd=c_dir,
        capture_output=True,
        timeout=30,
    )
    fortran_run = subprocess.run(
        [str(fortran_executable), *arguments],
        cwd=fortran_dir,
        capture_output=True,
        timeout=30,
    )
    return c_run, fortran_run


@pytest.mark.integration
@pytest.mark.corpus
@pytest.mark.skipif(
    shutil.which("gcc") is None or shutil.which("gfortran") is None,
    reason="gcc and gfortran are required",
)
@pytest.mark.parametrize("filename", NEWLY_SUPPORTED_EXAMPLES)
def test_newly_supported_example_matches_c_exactly(filename: str, tmp_path: Path) -> None:
    c_run, fortran_run = compile_transpile_and_run(CORPUS_DIR / filename, tmp_path)

    assert c_run.returncode == 0
    assert fortran_run.returncode == c_run.returncode
    # C and Fortran runtimes may use different native line endings on Windows.
    assert fortran_run.stdout.splitlines() == c_run.stdout.splitlines()
    assert fortran_run.stderr == c_run.stderr


@pytest.mark.integration
@pytest.mark.corpus
@pytest.mark.skipif(
    shutil.which("gfortran") is None,
    reason="gfortran is required",
)
@pytest.mark.parametrize("filename", ERRORS4_NUMERICAL_EXAMPLES)
def test_errors4_numerical_example_emits_compilable_fortran(
    filename: str, tmp_path: Path
) -> None:
    c_path = PROJECT_ROOT / "numerical_methods" / filename
    fortran_source = tmp_path / f"{c_path.stem}.f90"
    executable = tmp_path / f"{c_path.stem}.exe"
    fortran_source.write_text(
        xc2f.transpile_c_to_fortran(
            c_path.read_text(encoding="utf-8", errors="ignore")
        ),
        encoding="utf-8",
    )

    subprocess.run(
        [
            "gfortran",
            str(fortran_source),
            *xc2f.DEFAULT_GFORTRAN_FLAGS,
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
    )


@pytest.mark.integration
@pytest.mark.corpus
@pytest.mark.skipif(
    shutil.which("gcc") is None or shutil.which("gfortran") is None,
    reason="gcc and gfortran are required",
)
def test_numerical_mean_matches_c(tmp_path: Path) -> None:
    c_run, fortran_run = compile_transpile_and_run(
        PROJECT_ROOT / "numerical_methods" / "02_mean.c", tmp_path
    )

    assert c_run.returncode == fortran_run.returncode == 0
    assert fortran_run.stdout.splitlines() == c_run.stdout.splitlines()


@pytest.mark.integration
@pytest.mark.corpus
@pytest.mark.skipif(
    shutil.which("gcc") is None or shutil.which("gfortran") is None,
    reason="gcc and gfortran are required",
)
def test_command_line_arguments_match_c(tmp_path: Path) -> None:
    c_run, fortran_run = compile_transpile_and_run(
        CORPUS_DIR / "050_command_line_arguments.c",
        tmp_path,
        run_args=["alpha", "two words"],
    )

    # argv[0] is the executable path and necessarily differs between the two
    # isolated build directories. All remaining output must match exactly.
    c_lines = c_run.stdout.splitlines()
    fortran_lines = fortran_run.stdout.splitlines()
    assert c_run.returncode == fortran_run.returncode == 0
    assert c_lines[0] == fortran_lines[0] == b"argc = 3"
    assert c_lines[2:] == fortran_lines[2:]
    assert c_run.stderr == fortran_run.stderr


def normalize_leading_zeros(text: str) -> str:
    """Insert the leading zero Fortran's f0.d editing omits (".5" -> "0.5")."""
    return re.sub(r"(?<![0-9])\.(\d)", r"0.\1", text)


@pytest.mark.integration
@pytest.mark.corpus
@pytest.mark.skipif(
    shutil.which("gcc") is None or shutil.which("gfortran") is None,
    reason="gcc and gfortran are required",
)
def test_numerical_library_matches_c_numerically(tmp_path: Path) -> None:
    """xnumerical.c: typedef'd function pointers, copy-in by-value params,
    and discarded function results across a small numerical library."""
    c_run, fortran_run = compile_transpile_and_run(PROJECT_ROOT / "xnumerical.c", tmp_path)

    assert c_run.returncode == fortran_run.returncode == 0
    assert_semantically_equal_output(
        normalize_leading_zeros(c_run.stdout.decode("utf-8", errors="replace")),
        normalize_leading_zeros(fortran_run.stdout.decode("utf-8", errors="replace")),
    )


@pytest.mark.integration
@pytest.mark.corpus
@pytest.mark.skipif(
    shutil.which("gcc") is None or shutil.which("gfortran") is None,
    reason="gcc and gfortran are required",
)
def test_em_mixture_fit_runs_to_completion(tmp_path: Path) -> None:
    """xmv_mix.c: flattened multi-dimensional indexing must keep its explicit
    size dummies (regression: nobs was replaced by size of an nobs*ndim
    array, walking observation past the data and crashing)."""
    c_run, fortran_run = compile_transpile_and_run(PROJECT_ROOT / "xmv_mix.c", tmp_path)

    # rand() sequences differ, so values are not comparable, but the program
    # must complete and produce the full report with the same shape.
    assert c_run.returncode == fortran_run.returncode == 0
    c_lines = c_run.stdout.splitlines()
    fortran_lines = fortran_run.stdout.splitlines()
    assert len(fortran_lines) == len(c_lines)
    assert fortran_lines[:3] == c_lines[:3]  # nobs / ncomp / ndim


@pytest.mark.integration
@pytest.mark.corpus
@pytest.mark.skipif(
    shutil.which("gcc") is None or shutil.which("gfortran") is None,
    reason="gcc and gfortran are required",
)
def test_matrix_stats_stream_parsing_matches_c_numerically(tmp_path: Path) -> None:
    """xmatrix_stats.c: fgetc line reading, strtof cursors, and statistics.

    Formatting differs (%g field widths, header justification) but every label
    and number must agree token for token.
    """
    matrix_file = tmp_path / "matrix.txt"
    matrix_file.write_text(
        "1.0 2.0 3.5\n4.0 5.5 6.0\n7.25 8.0 9.0\n2.0 1.0 4.0\n",
        encoding="utf-8",
    )

    c_run, fortran_run = compile_transpile_and_run(
        PROJECT_ROOT / "xmatrix_stats.c",
        tmp_path,
        run_args=[str(matrix_file)],
    )

    assert c_run.returncode == fortran_run.returncode == 0
    assert_semantically_equal_output(
        c_run.stdout.decode("utf-8", errors="replace"),
        fortran_run.stdout.decode("utf-8", errors="replace"),
    )


@pytest.mark.integration
@pytest.mark.corpus
@pytest.mark.skipif(
    shutil.which("gcc") is None or shutil.which("gfortran") is None,
    reason="gcc and gfortran are required",
)
def test_random_numbers_translation_produces_values_in_range(tmp_path: Path) -> None:
    c_path = CORPUS_DIR / "073_random_numbers.c"
    c_run, fortran_run = compile_transpile_and_run(c_path, tmp_path)

    # C's rand() sequence and Fortran's default random seed are both
    # implementation-defined, so compare their portable observable behavior.
    assert c_run.returncode == fortran_run.returncode == 0
    for run in (c_run, fortran_run):
        values = [int(line) for line in run.stdout.splitlines()]
        assert len(values) == 10
        assert all(0 <= value <= 2_147_483_647 for value in values)


@pytest.mark.integration
@pytest.mark.corpus
@pytest.mark.skipif(
    shutil.which("gcc") is None or shutil.which("gfortran") is None,
    reason="gcc and gfortran are required",
)
def test_flexible_array_member_matches_c_numerically(tmp_path: Path) -> None:
    c_run, fortran_run = compile_transpile_and_run(
        CORPUS_DIR / "089_flexible_array_member.c",
        tmp_path,
    )

    # Fortran's width-zero F descriptor omits the leading zero for 0.00, but
    # the translated flexible-array values must otherwise match C exactly.
    assert c_run.returncode == fortran_run.returncode == 0
    assert [float(line) for line in fortran_run.stdout.splitlines()] == [
        float(line) for line in c_run.stdout.splitlines()
    ]


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
