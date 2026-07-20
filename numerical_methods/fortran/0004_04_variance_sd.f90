! created by xc2f.py from 04_variance_sd.c
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
public :: num_sd, num_variance
contains

pure function num_variance(x, n) result(num_variance_result)
! Return the sample variance of an array.
use, intrinsic :: ieee_arithmetic, only: ieee_value, ieee_quiet_nan
real(kind=dp), intent(in) :: x(:) ! data array
integer, intent(in) :: n ! problem size
real(kind=dp) :: num_variance_result
integer :: i
real(kind=dp) :: mean, sumsq
if (n < 2) then
   num_variance_result = ieee_value(0.0_dp, ieee_quiet_nan)
   return
end if
mean = 0.0_dp
sumsq = 0.0_dp
do i = 1, n
   mean = mean + x(i)
end do
mean = mean / n
do i = 1, n
   sumsq = sumsq + (x(i) - mean)**2
end do
num_variance_result = sumsq / (n - 1)
end function num_variance

pure function num_sd(x, n) result(num_sd_result)
! Return the sample standard deviation of an array.
real(kind=dp), intent(in) :: x(:) ! data array
integer, intent(in) :: n ! problem size
real(kind=dp) :: num_sd_result
num_sd_result = sqrt(real(num_variance(x, n), kind=dp))
end function num_sd

end module xc2f_mod

program main
use kind_mod, only: dp
! Test sample variance and standard deviation.
use xc2f_mod, only: num_sd, num_variance
implicit none
integer :: n
real(kind=dp) :: x(5)
x = real([(n, n=1,5)], kind=dp)
n = size(x) / 1
write(*, '("variance = ", f0.8)') num_variance(x, n)
write(*, '("sd       = ", f0.8)') num_sd(x, n)
end program main
