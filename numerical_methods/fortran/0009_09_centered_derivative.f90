! created by xc2f.py from 09_centered_derivative.c
module kind_mod
implicit none
private
public :: sp, dp
integer, parameter :: sp = kind(1.0)
integer, parameter :: dp = kind(1.0d0)
end module kind_mod

module xc2f_mod
use kind_mod, only: dp
implicit none
private
public :: num_derivative, test_function
contains

function num_derivative(f, x, h) result(num_derivative_result)
! Approximate a derivative using a centered difference.
use, intrinsic :: ieee_arithmetic, only: ieee_value, ieee_quiet_nan
procedure(test_function) :: f
real(kind=dp), intent(in) :: x ! data scalar value
real(kind=dp), intent(in) :: h
real(kind=dp) :: num_derivative_result
if (h <= 0.0_dp) then
   num_derivative_result = ieee_value(0.0_dp, ieee_quiet_nan)
   return
end if
num_derivative_result = (f(x + h) - f(x - h)) / (2.0_dp * h)
end function num_derivative

pure function test_function(x) result(test_function_result)
! Return sine of x.
real(kind=dp), intent(in) :: x ! data scalar value
real(kind=dp) :: test_function_result
test_function_result = sin(x)
end function test_function

end module xc2f_mod

program main
use kind_mod, only: dp
! Test centered numerical differentiation.
use xc2f_mod, only: num_derivative, test_function
implicit none
real(kind=dp), parameter :: x = 1.0_dp
write(*, '("estimate = ", f0.10)') num_derivative(test_function, x, h=1e-5_dp)
write(*, '("exact    = ", f0.10)') cos(x)
end program main
