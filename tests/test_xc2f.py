from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

import pytest

import fortran_scan
import xc2f


def test_gfortran_stops_after_first_compile_error() -> None:
    assert "-Wfatal-errors" in xc2f.DEFAULT_GFORTRAN_FLAGS


def test_debug_gfortran_flags_enable_full_runtime_diagnostics() -> None:
    normal = xc2f.gfortran_flags()
    debug = xc2f.gfortran_flags(debug=True)

    assert "-fcheck=all" not in normal
    assert "-fcheck=all" in debug
    assert "-g" in debug
    assert "-fbacktrace" in debug
    assert "-ffpe-trap=invalid,zero,overflow" in debug


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


def test_emitted_code_has_no_repeated_blank_lines_or_parenthesized_names() -> None:
    source = """
    int count_down(int ndim) {
        int i;
        int total = 0;
        for (i = 0; i < ndim; ++i) {
            total += ndim;
        }
        return total;
    }
    int main(void) { return count_down(3) == 9 ? 0 : 1; }
    """

    fortran = xc2f.transpile_c_to_fortran(source)

    assert "\n\n\n" not in fortran
    assert "(ndim)-1" not in fortran
    assert "do i = 0, ndim-1" in fortran


def test_integer_index_offsets_cancel_without_reassociating_reals() -> None:
    lines = [
        "program arithmetic\n",
        "integer :: n\n",
        "real :: x\n",
        "values((n - 1)+1) = 2.0\n",
        "next = (n + 2)+3\n",
        "x = (x - 1)+1\n",
        "end program arithmetic\n",
    ]

    result = "".join(fortran_scan.simplify_integer_arithmetic_in_lines(lines))

    assert "values(n) = 2.0" in result
    assert "next = n+5" in result
    assert "x = (x - 1)+1" in result


def test_transpiled_array_index_cancels_c_to_fortran_offset() -> None:
    source = """
    void set_last(double values[], int n, double final_value) {
        values[n - 1] = final_value;
    }
    int main(void) { return 0; }
    """

    fortran = xc2f.transpile_c_to_fortran(source)

    assert "values(n) = final_value" in fortran
    assert "values((n - 1)+1)" not in fortran


def test_compound_array_index_drops_redundant_arithmetic_parentheses() -> None:
    source = """
    double element(const double values[], int row, int n, int column) {
        return values[row * n + column];
    }
    int main(void) { return 0; }
    """

    fortran = xc2f.transpile_c_to_fortran(source)

    assert "values(row * n + column + 1)" in fortran
    assert "values(((row * n) + column) + 1)" not in fortran


def test_one_based_loop_normalization_is_configurable() -> None:
    source = """
    void fill(double result[], int n, double start, double step) {
        int i;
        for (i = 0; i < n; ++i) {
            result[i] = start + i * step;
        }
    }
    int main(void) { return 0; }
    """

    normalized = xc2f.transpile_c_to_fortran(source)
    translated = xc2f.transpile_c_to_fortran(source, one_based_loops=False)

    assert xc2f.NORMALIZE_ARRAY_LOOPS_TO_ONE_BASED is True
    assert "do i = 1, size(xresult)" in normalized
    assert "xresult(i) = start + (i - 1) * step" in normalized
    assert "do i = 0, (size(xresult))-1" in translated
    assert "xresult(i+1) = start + i * step" in translated


def test_integer_folding_precedes_do_bound_parentheses_cleanup() -> None:
    source = """
    double polynomial(const double coefficients[], int n, double x) {
        int i;
        double result = coefficients[n - 1];
        for (i = n - 1; i > 0; --i) {
            result = result * x + coefficients[i - 1];
        }
        return result;
    }
    int main(void) { return 0; }
    """

    fortran = xc2f.transpile_c_to_fortran(source)

    assert "do i = n - 1, 1, -1" in fortran
    assert "do i = n - 1, (0)+1, -1" not in fortran


def test_sizeof_fixed_array_divided_by_element_size_uses_array_size() -> None:
    source = """
    #include <stdio.h>
    int main(void) {
        double values[] = {1.0, 2.0, 3.0, 4.0};
        int count = sizeof(values) / sizeof(values[0]);
        printf("%d\\n", count);
        return 0;
    }
    """

    fortran = xc2f.transpile_c_to_fortran(source)

    assert "size(" in fortran
    assert "count = 1" not in fortran


def test_repeated_ieee_import_is_emitted_at_module_level() -> None:
    source = """
    #include <math.h>
    double first(int valid) { return valid ? 1.0 : NAN; }
    double second(int valid) { return valid ? 2.0 : NAN; }
    int main(void) { return first(1) + second(1) == 3.0 ? 0 : 1; }
    """

    fortran = xc2f.transpile_c_to_fortran(source)
    module_body = fortran.split("module xc2f_mod", 1)[1].split(
        "end module xc2f_mod", 1
    )[0]

    assert module_body.count("use, intrinsic :: ieee_arithmetic") == 1
    assert module_body.index("use, intrinsic :: ieee_arithmetic") < module_body.index(
        "contains"
    )


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


def test_safe_procedures_are_marked_pure_by_default() -> None:
    source = """
    int square(int value) {
        return value * value;
    }
    int main(void) { return square(3) == 9 ? 0 : 1; }
    """

    fortran = xc2f.transpile_c_to_fortran(source)

    assert "pure function square" in fortran.lower()


def test_purity_propagates_from_callee_to_caller() -> None:
    source = """
    void swap_double(double *a, double *b) {
        double temporary = *a;
        *a = *b;
        *b = temporary;
    }

    void swap_pairs(double values[], int count) {
        int i;
        for (i = 0; i + 1 < count; i += 2) {
            swap_double(&values[i], &values[i + 1]);
        }
    }

    int main(void) { return 0; }
    """

    fortran = xc2f.transpile_c_to_fortran(source)

    assert "pure subroutine swap_double" in fortran.lower()
    assert "pure subroutine swap_pairs" in fortran.lower()


def test_procedures_with_io_are_not_marked_pure() -> None:
    source = r'''
    #include <stdio.h>
    void report(int value) {
        printf("%d\n", value);
    }
    void report_twice(int value) {
        report(value);
        report(value);
    }
    int main(void) { report_twice(3); return 0; }
    '''

    fortran = xc2f.transpile_c_to_fortran(source)

    assert "subroutine report" in fortran.lower()
    assert "pure subroutine report" not in fortran.lower()
    assert "subroutine report_twice" in fortran.lower()
    assert "pure subroutine report_twice" not in fortran.lower()


def test_function_with_pointer_dummy_is_not_marked_pure() -> None:
    source = """
    typedef struct node {
        int value;
        struct node *next;
    } node;

    int sum_nodes(const node *item) {
        if (item == 0) return 0;
        return item->value + sum_nodes(item->next);
    }

    int main(void) { return 0; }
    """

    fortran = xc2f.transpile_c_to_fortran(source)

    assert "recursive function sum_nodes" in fortran.lower()
    assert "pure recursive function sum_nodes" not in fortran.lower()


def test_pure_promotion_can_be_disabled() -> None:
    source = """
    int square(int value) {
        return value * value;
    }
    int main(void) { return square(3) == 9 ? 0 : 1; }
    """

    fortran = xc2f.transpile_c_to_fortran(source, pure=False)

    assert "function square" in fortran.lower()
    assert "pure function square" not in fortran.lower()


def test_return_inside_for_loop_returns_from_function() -> None:
    source = """
    int find_first(const int values[], int count) {
        int i;
        for (i = 0; i < count; ++i) {
            if (values[i] > 0) {
                return i;
            }
        }
        return -1;
    }
    int main(void) { return 0; }
    """

    fortran = xc2f.transpile_c_to_fortran(source)
    function_body = fortran.split("function find_first", 1)[1].split(
        "end function find_first", 1
    )[0]

    assert "find_first_result = i - 1" in function_body
    assert "do i = 1, icount" in function_body
    assert "return" in function_body
    assert "stop" not in function_body


def test_writable_array_intent_propagates_through_wrapper() -> None:
    source = """
    void fill(double values[]) {
        values[0] = 1.0;
    }
    void wrapper(double values[]) {
        fill(values);
    }
    int main(void) {
        double values[1];
        wrapper(values);
        return 0;
    }
    """

    fortran = xc2f.transpile_c_to_fortran(source)
    wrapper_body = fortran.split("subroutine wrapper", 1)[1].split(
        "end subroutine wrapper", 1
    )[0]

    assert "intent(inout) :: values(:)" in wrapper_body


def test_isfinite_uses_ieee_intrinsic() -> None:
    fortran = transpile_main("double value = 1.0; if (!isfinite(value)) return 1;")

    assert "only: ieee_is_finite" in fortran
    assert "ieee_is_finite(" in fortran


def test_logical_not_of_integer_function_compares_with_zero() -> None:
    source = """
    int succeeds(void) { return 1; }
    int main(void) {
        if (!succeeds()) return 1;
        return 0;
    }
    """

    fortran = xc2f.transpile_c_to_fortran(source)

    assert "succeeds() == 0" in fortran
    assert ".not. (succeeds())" not in fortran


def test_unreachable_helper_is_not_emitted_with_main_program() -> None:
    source = """
    static int unused_helper(void) { return 42; }
    static int used_helper(void) { return 7; }
    int main(void) { return used_helper() == 7 ? 0 : 1; }
    """

    fortran = xc2f.transpile_c_to_fortran(source)

    assert "function used_helper" in fortran
    assert "function unused_helper" not in fortran


def test_file_scope_pointer_is_allocatable_array() -> None:
    source = """
    static double *shared_values = NULL;
    static void remember(const double values[]) { shared_values = values; }
    int main(void) {
        double values[2] = {1.0, 2.0};
        remember(values);
        return 0;
    }
    """

    fortran = xc2f.transpile_c_to_fortran(source)

    assert "real(kind=dp), allocatable :: shared_values(:)" in fortran
    assert "shared_values = values" in fortran


def test_pointer_to_array_element_becomes_array_section_view() -> None:
    source = """
    static double first(const double values[]) { return values[0]; }
    static double at_offset(const double data[], int offset) {
        const double *view = &data[offset];
        return first(view);
    }
    int main(void) {
        double data[2] = {1.0, 2.0};
        printf("%.1f\\n", at_offset(data, 1));
        return 0;
    }
    """

    fortran = xc2f.transpile_c_to_fortran(source)
    function_body = fortran.split("function at_offset", 1)[1].split(
        "end function at_offset", 1
    )[0]

    assert "allocatable :: view" not in function_body
    assert "view =" not in function_body
    assert "first(xdata(offset+1:))" in function_body


def test_fortran_keywords_are_renamed_in_all_identifier_contexts() -> None:
    source = """
    typedef struct { int dimension; } shape;
    int evaluate(int dimension, int select) {
        shape value = {.dimension = dimension};
        return select + value.dimension;
    }
    int main(void) { return evaluate(2, 1) == 3 ? 0 : 1; }
    """

    fortran = xc2f.transpile_c_to_fortran(source)

    assert "dimension" in fortran_scan.FORTRAN_KEYWORDS
    assert ":: dimension\n" not in fortran
    assert ":: select\n" not in fortran
    assert "%idimension" in fortran
    assert "idimension" in fortran
    assert "iselect" in fortran


def test_keyword_prefix_collision_appends_underscore() -> None:
    source = """
    int evaluate(int dimension, int idimension) {
        return dimension + idimension;
    }
    int main(void) { return evaluate(1, 2) == 3 ? 0 : 1; }
    """

    fortran = xc2f.transpile_c_to_fortran(source)
    lines = fortran.splitlines()

    assert "integer, intent(in) :: idimension_, idimension" in lines


def test_real_keyword_variable_uses_x_prefix() -> None:
    source = """
    double evaluate(double dimension) { return dimension * 2.0; }
    int main(void) { return evaluate(1.5) == 3.0 ? 0 : 1; }
    """

    fortran = xc2f.transpile_c_to_fortran(source)

    assert "real(kind=dp), intent(in) :: xdimension" in fortran


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
        compile=False,
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


def test_compile_builds_only_generated_fortran(tmp_path, monkeypatch) -> None:
    source = tmp_path / "hello.c"
    output = tmp_path / "hello.f90"
    source.write_text('int main(void) { return 0; }\n', encoding="utf-8")
    commands: list[list[str]] = []

    def fake_build(command, *, label):
        commands.append(command)
        assert label == "transformed-fortran"
        return True

    monkeypatch.setattr(xc2f, "_build_only_cmd", fake_build)
    monkeypatch.setattr(
        sys,
        "argv",
        ["xc2f.py", str(source), "--out", str(output), "--compile"],
    )

    assert xc2f.main() == 0
    assert len(commands) == 1
    assert commands[0][0] == "gfortran"
    assert "-c" not in commands[0]
    assert commands[0][-2:] == ["-o", str(output.with_suffix(".exe"))]


def test_cli_expands_c_file_globs(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "sources"
    output_dir = tmp_path / "fortran"
    source_dir.mkdir()
    (source_dir / "b.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    (source_dir / "a.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "xc2f.py",
            str(source_dir / "*.c"),
            "--out-dir",
            str(output_dir),
        ],
    )

    assert xc2f.main() == 0
    assert sorted(path.name for path in output_dir.glob("*.f90")) == ["a.f90", "b.f90"]


def test_cli_reports_unmatched_c_file_glob(tmp_path, monkeypatch, capsys) -> None:
    pattern = str(tmp_path / "missing" / "*.c")
    monkeypatch.setattr(sys, "argv", ["xc2f.py", pattern])

    assert xc2f.main() == 2
    assert f"No C files matched: {pattern}" in capsys.readouterr().out


def test_cli_can_disable_one_based_loop_normalization(tmp_path, monkeypatch) -> None:
    source = tmp_path / "loop.c"
    output = tmp_path / "loop.f90"
    source.write_text(
        "void fill(double x[], int n) { int i; "
        "for (i = 0; i < n; ++i) x[i] = i; }\n"
        "int main(void) { return 0; }\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "xc2f.py",
            str(source),
            "--out",
            str(output),
            "--no-one-based-loops",
        ],
    )

    assert xc2f.main() == 0
    fortran = output.read_text(encoding="utf-8")
    assert "do i = 0, (size(x))-1" in fortran
    assert "x(i+1) = i" in fortran


def test_debug_option_adds_debug_flags_to_compile_command(tmp_path, monkeypatch) -> None:
    source = tmp_path / "hello.c"
    output = tmp_path / "hello.f90"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    commands: list[list[str]] = []

    monkeypatch.setattr(
        xc2f,
        "_build_only_cmd",
        lambda command, *, label: commands.append(command) or True,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "xc2f.py",
            str(source),
            "--out",
            str(output),
            "--compile",
            "--debug",
        ],
    )

    assert xc2f.main() == 0
    assert len(commands) == 1
    for flag in xc2f.DEBUG_GFORTRAN_FLAGS:
        assert flag in commands[0]


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran is not installed")
def test_dynamic_struct_array_forwarding_and_fprintf_compile(tmp_path) -> None:
    source = r'''
    #include <stdio.h>
    #include <stdlib.h>

    typedef struct {
        int count;
        double *weight;
    } fit;

    static double first(const double values[], int count) {
        return count > 0 ? values[0] : 0.0;
    }

    static double forwarded(const double values[], int count) {
        return first(values, count);
    }

    static fit make_fit(int count) {
        fit result;
        result.count = count;
        result.weight = malloc((size_t)count * sizeof(*result.weight));
        if (result.weight == NULL) {
            fprintf(stderr, "allocation failed\n");
            exit(1);
        }
        return result;
    }

    int main(void) {
        fit result = make_fit(1);
        result.weight[0] = 1.0;
        printf("%.1f\n", forwarded(result.weight, result.count));
        free(result.weight);
        return 0;
    }
    '''
    fortran = xc2f.transpile_c_to_fortran(source)
    source_path = tmp_path / "struct_arrays.f90"
    executable_path = tmp_path / "struct_arrays.exe"
    source_path.write_text(fortran, encoding="utf-8")

    assert "real(kind=dp), allocatable :: weight(:)" in fortran
    assert "real(kind=dp), intent(in) :: values(:)" in fortran
    assert "allocated(make_fit_result%weight)" in fortran
    assert "call fprintf" not in fortran
    subprocess.run(
        [
            "gfortran",
            str(source_path),
            *xc2f.DEFAULT_GFORTRAN_FLAGS,
            "-o",
            str(executable_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran is not installed")
def test_numeric_pointer_return_with_realloc_and_feof_compiles(tmp_path) -> None:
    source = r'''
    #include <stdio.h>
    #include <stdlib.h>

    float *read_values(FILE *file, size_t *count) {
        float *values = NULL;
        size_t size = 0;
        size_t capacity = 0;
        float value;

        while (fscanf(file, "%f", &value) == 1) {
            if (size == capacity) {
                size_t new_capacity = capacity == 0 ? 16 : 2 * capacity;
                float *temporary = realloc(
                    values, new_capacity * sizeof(*values));
                if (temporary == NULL) {
                    free(values);
                    return NULL;
                }
                values = temporary;
                capacity = new_capacity;
            }
            values[size++] = value;
        }
        if (!feof(file)) {
            free(values);
            return NULL;
        }
        *count = size;
        return values;
    }

    int main(void) { return 0; }
    '''
    fortran = xc2f.transpile_c_to_fortran(source)
    source_path = tmp_path / "pointer_result.f90"
    executable_path = tmp_path / "pointer_result.exe"
    source_path.write_text(fortran, encoding="utf-8")

    assert "real(kind=sp), allocatable :: read_values_result(:)" in fortran
    assert "iostat=c2f_iostat" in fortran
    assert "feof(" not in fortran
    assert "call move_alloc(read_values_result_tmp, read_values_result)" in fortran
    subprocess.run(
        [
            "gfortran",
            str(source_path),
            *xc2f.DEFAULT_GFORTRAN_FLAGS,
            "-o",
            str(executable_path),
        ],
        check=True,
        capture_output=True,
        text=True,
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
