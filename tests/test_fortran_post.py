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


def test_space_offsets_after_compound_parenthesized_expression() -> None:
    lines = [
        "solution(i+1) = xsum / a(((i * n) + i)+1)\n",
        "value = a((row * n)-2)\n",
        "simple(i+1) = function(x)+1\n",
        'text = "a(((i * n) + i)+1)" ! keep )+1\n',
    ]

    assert fortran_post.space_compound_parenthesized_offsets(lines) == [
        "solution(i+1) = xsum / a(((i * n) + i) + 1)\n",
        "value = a((row * n) - 2)\n",
        "simple(i+1) = function(x)+1\n",
        'text = "a(((i * n) + i)+1)" ! keep )+1\n',
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


def test_coalesce_identical_intent_declarations_and_wrap_long_result() -> None:
    lines = [
        "real(kind=dp), intent(in) :: lower_arg\n",
        "real(kind=dp), intent(in) :: upper_arg\n",
        "real(kind=dp), intent(in) :: tolerance\n",
    ]

    assert fortran_scan.coalesce_simple_declarations(lines) == [
        "real(kind=dp), intent(in) :: lower_arg, upper_arg, tolerance\n"
    ]

    wrapped = fortran_scan.coalesce_simple_declarations(lines, max_len=55)
    assert wrapped == [
        "real(kind=dp), intent(in) :: lower_arg, upper_arg, &\n",
        "   & tolerance\n",
    ]


def test_coalesce_declarations_stops_at_trailing_comment() -> None:
    lines = [
        "real(kind=dp), intent(in) :: x ! data scalar value\n",
        "real(kind=dp), intent(in) :: step\n",
        "real(kind=dp) :: num_derivative_result\n",
    ]

    assert fortran_scan.coalesce_simple_declarations(lines) == lines


def test_declaration_wrapper_does_not_emit_comma_only_continuation() -> None:
    malformed = [
        "real(kind=dp) :: coefficients(4), grid(6), matrix(9), "
        "right_hand_side(3), root &\n",
        "& , &\n",
        "& solution(3), x(5), y(5)\n",
    ]

    wrapped = fortran_scan.wrap_long_declaration_lines(malformed, max_len=80)

    assert wrapped == [
        "real(kind=dp) :: coefficients(4), grid(6), matrix(9), "
        "right_hand_side(3), &\n",
        "   & root, solution(3), x(5), y(5)\n",
    ]
    assert all(len(line.rstrip("\r\n")) <= 80 for line in wrapped)
    assert not any(line.strip().startswith("& ,") for line in wrapped)


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


def test_shifted_index_loop_does_not_match_real_literal_prefix() -> None:
    lines = [
        "do state = 0, nstate - 1\n",
        "   probability(state + 1) = state + 1.0_dp\n",
        "end do\n",
    ]

    result = fortran_post.normalize_shifted_index_loops(lines)

    # Because the body uses state both as an index offset and in numeric
    # arithmetic, the conservative pass must leave the entire loop unchanged.
    assert result == lines


def test_collapse_consecutive_blank_lines_keeps_one() -> None:
    lines = [
        "program main\n",
        "\n",
        "   \n",
        "\n",
        "end program main\n",
    ]

    assert fortran_post.collapse_consecutive_blank_lines(lines) == [
        "program main\n",
        "\n",
        "end program main\n",
    ]


def test_combine_blank_write_with_following_character_write() -> None:
    lines = [
        '   write(*,"(a)") ""\n',
        '   write(*,"(a)") "true covariance:"\n',
        'write(*,"(a)") "" ! keep comment\n',
        'write(*,"(a)") "commented follower"\n',
        'write(7,"(a)") ""\n',
        'write(*,"(a)") "different unit"\n',
        'write(*,"(a)", advance="no") ""\n',
        'write(*,"(a)") "nonadvancing predecessor"\n',
    ]

    assert fortran_post.combine_blank_write_with_following_character_write(lines) == [
        '   write(*,"(/,a)") "true covariance:"\n',
        'write(*,"(a)") "" ! keep comment\n',
        'write(*,"(a)") "commented follower"\n',
        'write(7,"(a)") ""\n',
        'write(*,"(a)") "different unit"\n',
        'write(*,"(a)", advance="no") ""\n',
        'write(*,"(a)") "nonadvancing predecessor"\n',
    ]

def test_remove_parentheses_around_simple_variable_references() -> None:
    lines = [
        "do i = 0, (ndim)-1\n",
        "value = (state%mean) + ((offset))\n",
        "call consume((ndim))\n",
        "if (ready) then\n",
        "value = array(index)\n",
        "xsum = xsum + ifunction((lower + (i * step)))\n",
        "call pair((left + 1), (right * 2))\n",
        "z = cmplx((1.0, 2.0))\n",
        'text = "(ndim)" ! keep (comment%value)\n',
    ]

    assert fortran_post.remove_parentheses_around_variable_references(lines) == [
        "do i = 0, ndim-1\n",
        "value = state%mean + offset\n",
        "call consume(ndim)\n",
        "if (ready) then\n",
        "value = array(index)\n",
        "xsum = xsum + ifunction(lower + (i * step))\n",
        "call pair(left + 1, right * 2)\n",
        "z = cmplx((1.0, 2.0))\n",
        'text = "(ndim)" ! keep (comment%value)\n',
    ]


def test_remove_outer_parentheses_from_assignment_comparison_operands() -> None:
    lines = [
        "if (.not. cond_sc) cond_sc = "
        "((0.5_dp * abs(upper - lower)) < tolerance)\n",
        "converged = ((residual) <= (threshold))\n",
        "ratio = (x / (a + b))\n",
        "xsum = xsum - (a(index) * solution(column+1))\n",
    ]

    assert fortran_post.simplify_redundant_parentheses(lines) == [
        "if (.not. cond_sc) cond_sc = "
        "0.5_dp * abs(upper - lower) < tolerance\n",
        "converged = residual <= threshold\n",
        "ratio = x / (a + b)\n",
        "xsum = xsum - a(index) * solution(column+1)\n",
    ]

def test_simplify_neutral_logical_literals_in_nested_expression() -> None:
    lines = [
        "if ((.false. .or. (tolerance <= 0.0_dp)) .or. "
        "(max_iterations <= 0)) then\n",
        "valid = .true. .and. ready\n",
        "unchanged = .true. .or. evaluate()\n",
        "all_false = .false. .or. .false.\n",
    ]

    assert fortran_post.simplify_logical_identities(lines) == [
        "if (((tolerance <= 0.0_dp)) .or. (max_iterations <= 0)) then\n",
        "valid = ready\n",
        "unchanged = .true. .or. evaluate()\n",
        "all_false = .false.\n",
    ]


def test_remove_redundant_logical_operand_parentheses_by_precedence() -> None:
    lines = [
        "if (((tolerance <= 0.0_dp)) .or. (max_iterations <= 0)) then\n",
        "if ((ready .and. valid) .or. forced) then\n",
        "if ((ready .or. forced) .and. valid) then\n",
    ]

    assert fortran_post.simplify_redundant_parentheses(lines) == [
        "if (tolerance <= 0.0_dp .or. max_iterations <= 0) then\n",
        "if (ready .and. valid .or. forced) then\n",
        "if ((ready .or. forced) .and. valid) then\n",
    ]


def test_remove_literal_false_if_block() -> None:
    lines = [
        "if (.false.) then\n",
        "   if (allocated(a)) deallocate(a)\n",
        "   if (allocated(b)) deallocate(b)\n",
        "   num_solve_linear_result = 0\n",
        "   return\n",
        "end if\n",
        "call solve()\n",
    ]

    assert fortran_scan.simplify_constant_if_blocks(lines) == ["call solve()\n"]

def test_repeated_intrinsic_use_is_hoisted_to_module_scope() -> None:
    lines = [
        "module calculations\n",
        "implicit none\n",
        "contains\n",
        "function first() result(value)\n",
        "use, intrinsic :: ieee_arithmetic, only: ieee_value, ieee_quiet_nan\n",
        "real :: value\n",
        "end function first\n",
        "function second() result(value)\n",
        "use, intrinsic :: ieee_arithmetic, only: ieee_value, ieee_positive_inf\n",
        "real :: value\n",
        "end function second\n",
        "function one_off() result(value)\n",
        "use, intrinsic :: iso_fortran_env, only: int64\n",
        "integer :: value\n",
        "end function one_off\n",
        "end module calculations\n",
    ]

    result = fortran_post.hoist_module_use_only_imports(lines)
    text = "".join(result)

    assert text.count("use, intrinsic :: ieee_arithmetic") == 1
    assert (
        "use, intrinsic :: ieee_arithmetic, only: ieee_positive_inf, "
        "ieee_quiet_nan, ieee_value\nimplicit none\ncontains\n"
    ) in text
    assert text.count("use, intrinsic :: iso_fortran_env, only: int64") == 1
    assert text.index("contains\n") < text.index(
        "use, intrinsic :: iso_fortran_env, only: int64"
    )
