! created by xc2f.py from 12_bisection.c
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
public :: num_bisection, test_function
contains

function num_bisection(f, a_arg, b_arg, tol, maxit, root) &
& result(num_bisection_result)
! Find a root using the bisection method.
procedure(test_function) :: f
real(kind=dp), intent(in) :: a_arg ! input/output scalar
real(kind=dp), intent(in) :: b_arg ! input/output scalar
real(kind=dp), intent(in) :: tol
integer, intent(in) :: maxit
real(kind=dp), intent(inout) :: root
integer :: num_bisection_result, iter
real(kind=dp) :: a, b, fa, fb, fm, m
if (tol <= 0 .or. maxit <= 0) then
   num_bisection_result = 0
   return
end if
a = a_arg
b = b_arg
fa = f(a)
fb = f(b)
if (fa * fb > 0) then
   num_bisection_result = 0
   return
end if
do iter = 0, maxit-1
   m = 0.5_dp * (a + b)
   fm = f(m)
   block
      logical :: cond_sc
      cond_sc = abs(fm) < tol
      if (.not. cond_sc) cond_sc = 0.5_dp * abs(b - a) < tol
      if (cond_sc) then
         root = m
         num_bisection_result = 1
         return
      end if
   end block
   if (fa * fm <= 0) then
      b = m
      fb = fm
   else
      a = m
      fa = fm
   end if
end do
root = 0.5_dp * (a + b)
num_bisection_result = 0
end function num_bisection

pure function test_function(x) result(test_function_result)
! compute test_function
real(kind=dp), intent(in) :: x ! data scalar value
real(kind=dp) :: test_function_result
test_function_result = (x**2) - 2.0_dp
end function test_function

end module xc2f_mod

program main
use xc2f_mod, only: num_bisection, test_function
use kind_mod, only: dp
implicit none
real(kind=dp) :: root
write(*, '("success = ", i0, /, "root = ", f0.12, /, "exact = ", f0.12)') &
& num_bisection(test_function, a_arg=0.0_dp, b_arg=2.0_dp, tol=1e-12_dp, &
& maxit=1000, root=root), root, sqrt(real(2.0_dp, kind=dp))
end program main
