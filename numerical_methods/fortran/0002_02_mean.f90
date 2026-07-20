! created by xc2f.py from 02_mean.c
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
public :: num_mean
contains

pure function num_mean(x, n) result(num_mean_result)
! Return the arithmetic mean of an array.
use, intrinsic :: ieee_arithmetic, only: ieee_value, ieee_quiet_nan
real(kind=dp), intent(in) :: x(:) ! data array
integer, intent(in) :: n ! problem size
real(kind=dp) :: num_mean_result
integer :: i
real(kind=dp) :: xsum
if (n == 0) then
   num_mean_result = ieee_value(0.0_dp, ieee_quiet_nan)
   return
end if
xsum = 0.0_dp
do i = 1, n
   xsum = xsum + x(i)
end do
num_mean_result = xsum / n
end function num_mean

end module xc2f_mod

program main
use kind_mod, only: dp
! Test num_mean.
use xc2f_mod, only: num_mean
implicit none
real(kind=dp) :: x(5)
x = [1.0_dp, 2.0_dp, 3.0_dp, 4.0_dp, 5.0_dp]
write(*, '("mean = ", f0.8)') num_mean(x, size(x) / 1)
end program main
