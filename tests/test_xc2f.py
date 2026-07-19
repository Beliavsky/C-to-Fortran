from __future__ import annotations

import argparse
import shutil
import subprocess

import pytest

import xc2f


def test_gfortran_stops_after_first_compile_error() -> None:
    assert "-Wfatal-errors" in xc2f.DEFAULT_GFORTRAN_FLAGS


def transpile_main(body: str) -> str:
    source = f"""
    #include <stdio.h>

    int main(void) {{
        {body}
        return 0;
    }}
    """
    return xc2f.transpile_c_to_fortran(source)


def test_literal_printf_with_newline_preserves_text() -> None:
    fortran = transpile_main(r'printf("Hello, world!\n");')

    assert 'write(*,"(a)") "Hello, world!"' in fortran
    assert "approximated printf format" not in fortran


def test_literal_printf_without_newline_does_not_advance() -> None:
    fortran = transpile_main(r'printf("working...");')

    assert 'write(*,"(a)", advance="no") "working..."' in fortran


def test_literal_printf_decodes_escapes_and_percent() -> None:
    fortran = transpile_main(r'printf("tab:\t100%% \"done\"\n");')

    assert 'achar(9)' in fortran
    assert '100% ""done""' in fortran


def test_recursive_function_is_declared_recursive() -> None:
    source = """
    int factorial(int n) {
        if (n <= 1) return 1;
        return n * factorial(n - 1);
    }
    int main(void) { return 0; }
    """

    fortran = xc2f.transpile_c_to_fortran(source)

    assert "recursive function factorial" in fortran.lower()


def test_switch_fallthrough_is_rejected() -> None:
    source = """
    int main(void) {
        int value = 1;
        switch (value) {
            case 1:
                value += 1;
            case 2:
                value += 2;
                break;
        }
        return 0;
    }
    """

    with pytest.raises(NotImplementedError, match="fallthrough"):
        xc2f.transpile_c_to_fortran(source)


def test_inline_single_use_temp_preserves_expression_precedence() -> None:
    lines = [
        "program main\n",
        "implicit none\n",
        "real :: product, z\n",
        "z = 2.0 + 3.0\n",
        "product = z * 4.0\n",
        "print *, product\n",
        "end program main\n",
    ]

    text = "".join(xc2f.inline_single_use_temp_assignments(lines))

    assert "product = (2.0 + 3.0) * 4.0" in text


def test_compile_both_requires_both_compilers_to_succeed() -> None:
    args = argparse.Namespace(
        run_both=False,
        run=False,
        compile_both=True,
        compile_both_c=False,
        compile_c=False,
    )

    assert xc2f._requested_actions_succeeded(
        args,
        original_run_ok=False,
        original_build_ok=True,
        fortran_run_ok=False,
        fortran_build_ok=True,
    )
    assert not xc2f._requested_actions_succeeded(
        args,
        original_run_ok=False,
        original_build_ok=True,
        fortran_run_ok=False,
        fortran_build_ok=False,
    )


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran is not installed")
def test_generated_hello_world_runs(tmp_path) -> None:
    fortran_source = transpile_main(r'printf("Hello, world!\n");')
    source_path = tmp_path / "hello.f90"
    executable_path = tmp_path / "hello.exe"
    source_path.write_text(fortran_source, encoding="utf-8")

    subprocess.run(
        ["gfortran", str(source_path), "-o", str(executable_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    completed = subprocess.run(
        [str(executable_path)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout == "Hello, world!\n"
