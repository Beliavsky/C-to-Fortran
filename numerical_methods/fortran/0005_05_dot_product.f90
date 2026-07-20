! created by xc2f.py from 05_dot_product.c
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
public :: num_dot
contains

pure function num_dot(x, y, n) result(num_dot_result)
! Return the dot product of two arrays.
real(kind=dp), intent(in) :: x(:) ! data array
real(kind=dp), intent(in) :: y(:) ! data array
integer, intent(in) :: n ! problem size
real(kind=dp) :: num_dot_result
integer :: i
num_dot_result = 0.0_dp
do i = 1, n
   num_dot_result = num_dot_result + x(i) * y(i)
end do
end function num_dot

end module xc2f_mod

program main
use kind_mod, only: dp
! Test num_dot.
use xc2f_mod, only: num_dot
implicit none
write(*, '("dot = ", f0.8)') num_dot(([1.0_dp, 2.0_dp, 3.0_dp]), [4.0_dp, &
& 5.0_dp, 6.0_dp], 3)
end program main
