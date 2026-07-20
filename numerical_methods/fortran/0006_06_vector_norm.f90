! created by xc2f.py from 06_vector_norm.c
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
public :: num_norm
contains

pure function num_norm(x) result(num_norm_result)
! Return the Euclidean norm of an array.
real(kind=dp), intent(in) :: x(:) ! data array
real(kind=dp) :: num_norm_result
integer :: i
real(kind=dp) :: sumsq
sumsq = 0.0_dp
do i = 1, size(x)
   sumsq = sumsq + x(i)**2
end do
num_norm_result = sqrt(sumsq)
end function num_norm

end module xc2f_mod

program main
use kind_mod, only: dp
! Test num_norm.
use xc2f_mod, only: num_norm
implicit none
write(*, '("norm = ", f0.8)') num_norm([3.0_dp, 4.0_dp])
end program main
