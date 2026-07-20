! created by xc2f.py from 13_newton.c
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
public :: df, f, num_newton
contains

function num_newton(f_proc, df_proc, x_arg, tol, maxit, root) &
& result(num_newton_result)
! Find a root using Newton's method.
real(kind=dp), parameter :: NUM_TOL = 1.0e-14_dp
procedure(f) :: f_proc
procedure(df) :: df_proc
real(kind=dp), intent(in) :: x_arg ! data scalar value
real(kind=dp), intent(in) :: tol
integer, intent(in) :: maxit
real(kind=dp), intent(inout) :: root
integer :: num_newton_result, iter
real(kind=dp) :: dfx, fx, next, x
if (tol <= 0 .or. maxit <= 0) then
   num_newton_result = 0
   return
end if
x = x_arg
do iter = 0, maxit-1
   fx = f_proc(x)
   dfx = df_proc(x)
   if (abs(fx) < tol) then
      root = x
      num_newton_result = 1
      return
   end if
   if (abs(dfx) < NUM_TOL) then
      num_newton_result = 0
      return
   end if
   next = x - fx / dfx
   if (abs(next - x) < tol) then
      root = next
      num_newton_result = 1
      return
   end if
   x = next
end do
root = x
num_newton_result = 0
end function num_newton

pure function f(x) result(f_result)
! compute f
real(kind=dp), intent(in) :: x ! data scalar value
real(kind=dp) :: f_result
f_result = (x**2) - 2.0_dp
end function f

pure function df(x) result(df_result)
! compute df
real(kind=dp), intent(in) :: x ! data scalar value
real(kind=dp) :: df_result
df_result = 2.0_dp * x
end function df

end module xc2f_mod

program main
use xc2f_mod, only: df, f, num_newton
use kind_mod, only: dp
implicit none
real(kind=dp) :: root
write(*, '("success = ", i0, /, "root = ", f0.12, /, "exact = ", f0.12)') &
& num_newton(f, df, x_arg=1.0_dp, tol=1e-12_dp, maxit=100, &
& root=root), root, sqrt(real(2.0_dp, kind=dp))
end program main
