! created by xc2f.py from 07_linspace.c
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
public :: num_linspace
contains

function num_linspace(start, xend, n, xresult) result(num_linspace_result)
! Fill an array with equally spaced values.
real(kind=dp), intent(in) :: start, xend
integer, intent(in) :: n ! problem size
real(kind=dp), intent(inout) :: xresult(:)
integer :: num_linspace_result, i
real(kind=dp) :: step
if (n == 0) then
   num_linspace_result = 0
   return
end if
if (n == 1) then
   xresult(1) = start
   num_linspace_result = 1
   return
end if
step = (xend - start) / (n - 1)
do i = 1, n
   xresult(i) = start + (i - 1) * step
end do
xresult(n) = xend
num_linspace_result = 1
end function num_linspace

end module xc2f_mod

program main
use kind_mod, only: dp
! Test num_linspace.
use xc2f_mod, only: num_linspace
implicit none
integer :: i
real(kind=dp) :: x(6)
if (num_linspace(0.0_dp, 1.0_dp, 6, x) == 0) stop
do i = 1, 6
   write(*, '(i0, " ", f0.8)') (i - 1), x(i)
end do
end program main
