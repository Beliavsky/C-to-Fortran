! created by xc2f.py from 10_trapezoidal_integration.c
module kind_mod
implicit none
private
public :: dp
integer, parameter :: dp = kind(1.0d0)
end module kind_mod

module xc2f_mod
use kind_mod, only: dp
implicit none
private
public :: num_integrate_trapezoid, test_function
contains

function num_integrate_trapezoid(f, a, b, n) &
& result(num_integrate_trapezoid_result)
! Integrate a function using the trapezoidal rule.
use, intrinsic :: ieee_arithmetic, only: ieee_value, ieee_quiet_nan
procedure(test_function) :: f
real(kind=dp), intent(in) :: a ! input scalar coefficient
real(kind=dp), intent(in) :: b ! input scalar coefficient
integer, intent(in) :: n ! problem size
real(kind=dp) :: num_integrate_trapezoid_result
integer :: i
real(kind=dp) :: h, xsum
if (n == 0) then
   num_integrate_trapezoid_result = ieee_value(0.0_dp, ieee_quiet_nan)
   return
end if
h = (b - a) / n
xsum = 0.5_dp * (f(a) + f(b))
do i = 1, n-1
   xsum = xsum + f(a + i * h)
end do
num_integrate_trapezoid_result = h * xsum
end function num_integrate_trapezoid

pure function test_function(x) result(test_function_result)
! compute test_function
real(kind=dp), intent(in) :: x ! data scalar value
real(kind=dp) :: test_function_result
test_function_result = sin(x)
end function test_function

end module xc2f_mod

program main
use xc2f_mod, only: num_integrate_trapezoid, test_function
use kind_mod, only: dp
implicit none
real(kind=dp), parameter :: PI = 3.14159265358979323846_dp
write(*, '("integral = ", f0.10)') num_integrate_trapezoid(test_function, &
& a=0.0_dp, b=PI, n=10000)
write(*, '("exact    = ", f0.10)') 2.0_dp
end program main
