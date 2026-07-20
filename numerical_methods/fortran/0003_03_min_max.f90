! created by xc2f.py from 03_min_max.c
module kind_mod
implicit none
private
public :: sp, dp
integer, parameter :: sp = kind(1.0)
integer, parameter :: dp = kind(1.0d0)
end module kind_mod

module xc2f_mod
use kind_mod, only: dp
use, intrinsic :: ieee_arithmetic, only: ieee_quiet_nan, ieee_value
implicit none
private
public :: num_max, num_min
contains

pure function num_min(x, n) result(num_min_result)
! Return the minimum value in an array.
real(kind=dp), intent(in) :: x(:) ! data array
integer, intent(in) :: n ! problem size
real(kind=dp) :: num_min_result
integer :: i
if (n == 0) then
   num_min_result = ieee_value(0.0_dp, ieee_quiet_nan)
   return
end if
num_min_result = x(1)
do i = 2, n
   if (x(i) < num_min_result) num_min_result = x(i)
end do
end function num_min

pure function num_max(x, n) result(num_max_result)
! Return the maximum value in an array.
real(kind=dp), intent(in) :: x(:) ! data array
integer, intent(in) :: n ! problem size
real(kind=dp) :: num_max_result
integer :: i
if (n == 0) then
   num_max_result = ieee_value(0.0_dp, ieee_quiet_nan)
   return
end if
num_max_result = x(1)
do i = 2, n
   if (x(i) > num_max_result) num_max_result = x(i)
end do
end function num_max

end module xc2f_mod

program main
use kind_mod, only: dp
! Test num_min and num_max.
use xc2f_mod, only: num_max, num_min
implicit none
integer :: n
real(kind=dp) :: x(5)
x = [4.0_dp, -2.0_dp, 8.0_dp, 3.0_dp, 1.0_dp]
n = size(x) / 1
write(*, '("min = ", f0.8)') num_min(x, n)
write(*, '("max = ", f0.8)') num_max(x, n)
end program main
