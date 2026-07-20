"""Regression tests for C stream I/O, string-cursor, and by-value lowerings.

These cover the machinery added for xmatrix_stats.c / xnumerical.c /
xmv_mix.c: fgetc loops, char* cursors with strtof, NULL-string sentinels,
copy-in by-value parameters, typedef'd function pointers, discarded function
results, and the compiler-pass bugs found along the way.
"""

from __future__ import annotations

import pytest

import fortran_scan as fscan
import xc2f


READ_LINE_SOURCE = r"""
#include <stdio.h>
#include <stdlib.h>

static char *read_line(FILE *file) {
    char *line = NULL;
    size_t length = 0;
    int ch;

    while ((ch = fgetc(file)) != EOF) {
        if (ch == '\n') {
            break;
        }
        line[length++] = (char)ch;
    }
    if (ch == EOF && length == 0) {
        free(line);
        return NULL;
    }
    line[length] = '\0';
    return line;
}

int main(void) {
    FILE *f = fopen("in.txt", "r");
    char *line;
    while ((line = read_line(f)) != NULL) {
        printf("%s\n", line);
        free(line);
    }
    fclose(f);
    return 0;
}
"""

PARSE_ROW_SOURCE = r"""
#include <ctype.h>
#include <stdlib.h>

static int parse_row(const char *line, float **values, size_t *count) {
    float *row = NULL;
    size_t size = 0;
    const char *position = line;
    while (*position != '\0') {
        char *end;
        float value;
        while (isspace((unsigned char)*position)) {
            ++position;
        }
        if (*position == '\0') {
            break;
        }
        value = strtof(position, &end);
        if (end == position) {
            free(row);
            return 0;
        }
        row = realloc(row, (size + 1) * sizeof(*row));
        row[size++] = value;
        position = end;
    }
    *values = row;
    *count = size;
    return 1;
}

int main(void) {
    float *vals;
    size_t n;
    if (!parse_row("1.5 2.5", &vals, &n)) {
        return 1;
    }
    printf("%zu\n", n);
    free(vals);
    return 0;
}
"""

BY_VALUE_AND_FUNCPTR_SOURCE = r"""
#include <stdio.h>

typedef double (*num_function)(double);

double square(double x) {
    return x * x;
}

double bracket(num_function f, double lower, double upper) {
    while (upper - lower > 1.0e-6) {
        lower = 0.5 * (lower + upper);
        upper = upper - 0.25 * (upper - lower);
    }
    return f(lower);
}

int fill(double values[], int n) {
    int i;
    if (values == NULL || n == 0) {
        return 0;
    }
    for (i = 0; i < n; ++i) {
        values[i] = i;
    }
    return 1;
}

int main(void) {
    double x[4];
    fill(x, 4);
    printf("%.3f %f\n", bracket(square, 1.0, 2.0), x[2]);
    return 0;
}
"""


@pytest.fixture(scope="module")
def read_line_fortran() -> str:
    return xc2f.transpile_c_to_fortran(READ_LINE_SOURCE)


@pytest.fixture(scope="module")
def parse_row_fortran() -> str:
    return xc2f.transpile_c_to_fortran(PARSE_ROW_SOURCE)


@pytest.fixture(scope="module")
def by_value_fortran() -> str:
    return xc2f.transpile_c_to_fortran(BY_VALUE_AND_FUNCPTR_SOURCE)


def test_assignment_in_while_condition_is_reemitted(read_line_fortran: str) -> None:
    # while ((ch = fgetc(f)) != EOF) must evaluate the call every pass.
    assert "ch = c2f_fgetc(file)" in read_line_fortran
    assert "if (.not. (ch /= (-1))) exit" in read_line_fortran


def test_fgetc_helper_maps_eol_and_eof(read_line_fortran: str) -> None:
    assert "function c2f_fgetc(unit)" in read_line_fortran
    assert "iostat_eor" in read_line_fortran
    assert "ch = 10" in read_line_fortran  # '\n' at end of record
    assert "ch = -1" in read_line_fortran  # EOF


def test_char_constant_compares_ordinal_against_int(read_line_fortran: str) -> None:
    # `ch == '\n'` with an int ch compares character codes.
    assert "if (ch == 10) exit" in read_line_fortran


def test_char_store_grows_string_via_helper(read_line_fortran: str) -> None:
    # line[length++] = (char)ch: achar conversion plus a growing store.
    assert "call c2f_setchar(read_line_result, length+1, achar(ch))" in read_line_fortran
    assert "subroutine c2f_setchar(s, i, c)" in read_line_fortran


def test_nul_store_truncates_string(read_line_fortran: str) -> None:
    # line[length] = '\0' fixes the logical length.
    assert "read_line_result = read_line_result(1:length)" in read_line_fortran


def test_null_char_pointer_uses_nul_sentinel(read_line_fortran: str) -> None:
    # return NULL -> the one-char NUL string; caller tests against it.
    assert "read_line_result = achar(0)" in read_line_fortran
    assert "(line /= achar(0))" in read_line_fortran


def test_cursor_init_deref_and_bound_check(parse_row_fortran: str) -> None:
    # const char *position = line -> integer position starting at 1;
    # *position != '\0' -> a bound test; *position reads one character.
    assert "position = 1" in parse_row_fortran
    assert "(position <= len(line))" in parse_row_fortran
    assert "line(position:position)" in parse_row_fortran


def test_strtof_lowered_to_helper_with_end_cursor(parse_row_fortran: str) -> None:
    assert "c2f_strtof(line, position, send)" in parse_row_fortran
    assert "function c2f_strtof(s, pos, endpos)" in parse_row_fortran
    # A failed parse leaves the end cursor at the start position.
    assert "(send == position)" in parse_row_fortran


def test_isspace_helper_takes_character_code(parse_row_fortran: str) -> None:
    assert "c2f_isspace(ichar(line(position:position)))" in parse_row_fortran
    assert "function c2f_isspace(ic)" in parse_row_fortran


def test_double_pointer_out_param_is_allocatable_array(parse_row_fortran: str) -> None:
    # float **values with *values = row stores a whole array.
    assert "real(kind=sp), allocatable, intent(out) :: values(:)" in parse_row_fortran
    assert "values = row" in parse_row_fortran


def test_reassigned_by_value_param_gets_local_copy(by_value_fortran: str) -> None:
    # C by-value params are local copies; literals must remain passable.
    assert "real(kind=dp), intent(in) :: lower_arg" in by_value_fortran
    assert "lower = lower_arg" in by_value_fortran
    assert "upper = upper_arg" in by_value_fortran


def test_typedef_function_pointer_param_is_procedure_dummy(by_value_fortran: str) -> None:
    assert "procedure(square) :: f" in by_value_fortran


def test_value_returning_function_statement_discards_result(by_value_fortran: str) -> None:
    # fill(x, 4); as a statement cannot be CALLed in Fortran.
    assert "discarded_result = fill(" in by_value_fortran
    assert "call fill(" not in by_value_fortran


def test_null_check_on_array_dummy_folds_to_constant(by_value_fortran: str) -> None:
    # values == NULL is meaningless for an assumed-shape dummy.
    assert "if (n == 0) then" in by_value_fortran
    assert ".false. .or. (n == 0)" not in by_value_fortran


def test_char_cast_from_int_uses_achar() -> None:
    # Regression: cast target types arrive wrapped in a Typename; (char)n
    # must become achar(n), not int(n).
    source = r"""
    #include <stdio.h>
    int main(void) {
        char text[8];
        int code = 65;
        text[0] = (char)code;
        text[1] = '\0';
        printf("%s\n", text);
        return 0;
    }
    """
    fortran = xc2f.transpile_c_to_fortran(source)
    assert "achar(code)" in fortran


def test_pointer_section_alias_indexing_folds_into_one_subscript() -> None:
    # const double *row_ptr = &data[obs * 3]; row_ptr[1] must be one element,
    # not a section followed by another subscript.
    source = r"""
    #include <stdio.h>
    int main(void) {
        double data[6] = {1, 2, 3, 4, 5, 6};
        int obs;
        for (obs = 0; obs < 2; ++obs) {
            const double *row_ptr = &data[obs * 3];
            printf("%f\n", row_ptr[1]);
        }
        return 0;
    }
    """
    fortran = xc2f.transpile_c_to_fortran(source)
    assert "xdata(((obs * 3)) + (1)+1)" in fortran
    assert ":)(" not in fortran  # never a section indexed again


def test_promotion_counts_one_line_if_assignment() -> None:
    # `if (...) r = 1` reassigns r: r must stay a variable.
    lines = [
        "function f(ic) result(r)\n",
        "integer, intent(in) :: ic\n",
        "integer :: r\n",
        "r = 0\n",
        "if (ic == 32) r = 1\n",
        "end function f\n",
    ]
    text = "".join(fscan.promote_scalar_constants_to_parameters(lines))
    assert "parameter" not in text.lower()


def test_promotion_skips_function_result_variable() -> None:
    lines = [
        "function g() result(r)\n",
        "integer :: r\n",
        "r = 0\n",
        "end function g\n",
    ]
    text = "".join(fscan.promote_scalar_constants_to_parameters(lines))
    assert "parameter" not in text.lower()


def test_dead_store_keeps_declaration_with_side_effecting_assignment() -> None:
    # The assignment stays because its RHS may have side effects, so the
    # declaration must stay with it.
    lines = [
        "program main\n",
        "implicit none\n",
        "integer :: unused_v\n",
        "unused_v = do_work(3)\n",
        "end program main\n",
    ]
    text = "".join(xc2f.apply_dead_store_cleanup(lines))
    assert "integer :: unused_v" in text
    assert "unused_v = do_work(3)" in text
