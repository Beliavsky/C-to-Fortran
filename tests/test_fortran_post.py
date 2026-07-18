from __future__ import annotations

import fortran_post
import fortran_scan


def test_tighten_unary_minus_spacing_does_not_modify_strings() -> None:
    lines = [
        'value = - 1.5_dp\n',
        'print *, "range - 1 and quote ""- 2"""\n',
        "print *, 'range - 3 and quote ''- 4'''\n",
    ]

    result = fortran_post.tighten_unary_minus_literal_spacing(lines)

    assert result == [
        'value = -1.5_dp\n',
        'print *, "range - 1 and quote ""- 2"""\n',
        "print *, 'range - 3 and quote ''- 4'''\n",
    ]


def test_parameter_promotion_skips_procedure_actual_arguments() -> None:
    lines = [
        "program main\n",
        "implicit none\n",
        "integer :: fixed, mutated\n",
        "fixed = 10\n",
        "mutated = 20\n",
        "call update(mutated)\n",
        "print *, fixed, mutated\n",
        "end program main\n",
    ]

    result = fortran_scan.promote_scalar_constants_to_parameters(lines)
    text = "".join(result)

    assert "integer, parameter :: fixed = 10" in text
    assert "integer :: mutated" in text
    assert "mutated = 20" in text


def test_reserved_result_variable_rename_preserves_function_syntax() -> None:
    lines = [
        "function compute() result(compute_result)\n",
        "integer :: compute_result, result\n",
        "result = 1\n",
        "compute_result = result\n",
        "end function compute\n",
    ]

    text = "".join(fortran_scan.avoid_reserved_identifier_definitions(lines))

    assert "function compute() result(compute_result)" in text
    assert "integer :: compute_result, result_v" in text
