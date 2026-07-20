! created by xc2f.py from 08_polynomial_horner.c
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
public :: num_polynomial
contains

pure function num_polynomial(coefficients, n, x) result(num_polynomial_result)
! Evaluate a polynomial using Horner's method.
real(kind=dp), intent(in) :: coefficients(:)
integer, intent(in) :: n ! problem size
real(kind=dp), intent(in) :: x ! data scalar value
real(kind=dp) :: num_polynomial_result
integer :: i
if (n == 0) then
   num_polynomial_result = 0.0_dp
   return
end if
num_polynomial_result = coefficients(n)
do i = n - 1, 1, -1
   num_polynomial_result = (num_polynomial_result * x) + coefficients(i)
end do
end function num_polynomial

end module xc2f_mod

program main
use kind_mod, only: dp
! Test polynomial evaluation.
use xc2f_mod, only: num_polynomial
implicit none
write(*, '("value = ", f0.8)') num_polynomial([1.0_dp, -2.0_dp, 0.0_dp, 3.0_dp &
& ], 4, 2.0_dp)
end program main
