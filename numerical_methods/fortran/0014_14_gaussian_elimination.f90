! created by xc2f.py from 14_gaussian_elimination.c
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
public :: num_solve_linear
contains

function num_solve_linear(matrix, rhs, n, solution) &
& result(num_solve_linear_result)
! Solve a dense linear system using Gaussian elimination.
real(kind=dp), parameter :: NUM_TOL = 1.0e-12_dp
real(kind=dp), intent(in) :: matrix(:), rhs(:)
integer, intent(in) :: n ! problem size
real(kind=dp), intent(inout) :: solution(:)
integer :: num_solve_linear_result, best, col, i, pivot, row
real(kind=dp) :: bestv, factor, t, xsum
real(kind=dp), allocatable :: a(:), b(:)
allocate(a(n * n), b(n))
if (n == 0) then
   if (allocated(a)) deallocate(a)
   if (allocated(b)) deallocate(b)
   num_solve_linear_result = 0
   return
end if
do row = 1, n
   b(row) = rhs(row)
   do col = 0, n-1
      a((row - 1) * n + col + 1) = matrix((row - 1) * n + col + 1)
   end do
end do
do pivot = 1, n
   best = pivot - 1
   bestv = abs(a((pivot - 1) * n + pivot))
   do row = pivot, n-1
      if (abs(a(row * n + pivot)) > bestv) then
         bestv = abs(a(row * n + pivot))
         best = row
      end if
   end do
   if (bestv < NUM_TOL) then
      if (allocated(a)) deallocate(a)
      if (allocated(b)) deallocate(b)
      num_solve_linear_result = 0
      return
   end if
   if (best /= pivot - 1) then
      do col = 0, n-1
         t = a((pivot - 1) * n + col + 1)
         a((pivot - 1) * n + col + 1) = a(best * n + col + 1)
         a(best * n + col + 1) = t
      end do
      t = b(pivot)
      b(pivot) = b(best+1)
      b(best+1) = t
   end if
   do row = pivot, n-1
      factor = a(row * n + pivot) / a((pivot - 1) * n + pivot)
      a(row * n + pivot) = 0.0_dp
      do col = pivot, n-1
         a(row * n + col + 1) = a(row * n + col + 1) - factor * a((pivot - 1) &
         & * n + col + 1)
      end do
      b(row+1) = b(row+1) - factor * b(pivot)
   end do
end do
do row = n, 1, -1
   i = row - 1
   xsum = b(i+1)
   do col = i + 1, n-1
      xsum = xsum - a(i * n + col + 1) * solution(col+1)
   end do
   solution(i+1) = xsum / a(i * n + i + 1)
end do
if (allocated(a)) deallocate(a)
if (allocated(b)) deallocate(b)
num_solve_linear_result = 1
end function num_solve_linear

end module xc2f_mod

program main
use xc2f_mod, only: num_solve_linear
use kind_mod, only: dp
implicit none
real(kind=dp) :: a(9), b(3), x(3)
a = [3.0_dp, 2.0_dp, -1.0_dp, 2.0_dp, -2.0_dp, 4.0_dp, -1.0_dp, 0.5_dp, -1.0_dp]
b = [1.0_dp, -2.0_dp, 0.0_dp]
x = [0.0_dp, 0.0_dp, 0.0_dp]
write(*, '("success = ", i0, /, "x1 = ", f0.8, /, "x2 = ", f0.8, /, "x3 = ", f0.8)') num_solve_linear(a, b, n=3, solution=x), x(1), x(2), x(3)
end program main
