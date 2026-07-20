! created by xc2f.py from 01_sum.c
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
public :: num_sum
contains

pure function num_sum(x) result(num_sum_result)
! Return the sum of an array.
real(kind=dp), intent(in) :: x(:) ! data array
real(kind=dp) :: num_sum_result
integer :: i
num_sum_result = 0.0_dp
do i = 1, size(x)
   num_sum_result = num_sum_result + x(i)
end do
end function num_sum

end module xc2f_mod

program main
use kind_mod, only: dp
! Test num_sum.
use xc2f_mod, only: num_sum
implicit none
write(*, '("sum = ", f0.8)') num_sum(([1.0_dp, 2.0_dp, 3.0_dp, 4.0_dp, 5.0_dp]))
end program main
