! created by xc2f.py from 11_simpson_integration.c
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
public :: num_integrate_simpson, test_function
contains

function num_integrate_simpson(f, a, b, n) result(num_integrate_simpson_result)
! Integrate a function using Simpson's rule.
use, intrinsic :: ieee_arithmetic, only: ieee_value, ieee_quiet_nan
procedure(test_function) :: f
real(kind=dp), intent(in) :: a ! input scalar coefficient
real(kind=dp), intent(in) :: b ! input scalar coefficient
integer, intent(in) :: n ! problem size
real(kind=dp) :: num_integrate_simpson_result
integer :: i
real(kind=dp) :: h, xsum
if (n == 0 .or. mod(n, 2) /= 0) then
   num_integrate_simpson_result = ieee_value(0.0_dp, ieee_quiet_nan)
   return
end if
h = (b - a) / n
xsum = f(a) + f(b)
do i = 1, n-1
   xsum = xsum + merge(2.0_dp, 4.0_dp, mod(i, 2) == 0) * f(a + i * h)
end do
num_integrate_simpson_result = (h * xsum) / 3.0_dp
end function num_integrate_simpson

pure function test_function(x) result(test_function_result)
! compute test_function
real(kind=dp), intent(in) :: x ! data scalar value
real(kind=dp) :: test_function_result
test_function_result = sin(x)
end function test_function

end module xc2f_mod

program main
use xc2f_mod, only: num_integrate_simpson, test_function
use kind_mod, only: dp
implicit none
real(kind=dp), parameter :: PI = 3.14159265358979323846_dp
write(*, '("integral = ", f0.10)') num_integrate_simpson(test_function, &
& a=0.0_dp, b=PI, n=1000)
write(*, '("exact    = ", f0.10)') 2.0_dp
end program main
