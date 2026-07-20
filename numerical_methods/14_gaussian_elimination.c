#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#define NUM_TOL 1.0e-12

/* Solve a dense linear system using Gaussian elimination. */
static int num_solve_linear(const double matrix[], const double rhs[], size_t n, double solution[]) {
    double *a = malloc(n * n * sizeof(*a));
    double *b = malloc(n * sizeof(*b));
    size_t pivot, row, col;
    if (matrix == NULL || rhs == NULL || solution == NULL || n == 0 || a == NULL || b == NULL) { free(a); free(b); return 0; }
    for (row = 0; row < n; ++row) { b[row] = rhs[row]; for (col = 0; col < n; ++col) a[row*n+col] = matrix[row*n+col]; }
    for (pivot = 0; pivot < n; ++pivot) {
        size_t best = pivot; double bestv = fabs(a[pivot*n+pivot]);
        for (row = pivot + 1; row < n; ++row) if (fabs(a[row*n+pivot]) > bestv) { bestv = fabs(a[row*n+pivot]); best = row; }
        if (bestv < NUM_TOL) { free(a); free(b); return 0; }
        if (best != pivot) {
            for (col = 0; col < n; ++col) { double t = a[pivot*n+col]; a[pivot*n+col] = a[best*n+col]; a[best*n+col] = t; }
            { double t = b[pivot]; b[pivot] = b[best]; b[best] = t; }
        }
        for (row = pivot + 1; row < n; ++row) {
            double factor = a[row*n+pivot] / a[pivot*n+pivot]; a[row*n+pivot] = 0.0;
            for (col = pivot + 1; col < n; ++col) a[row*n+col] -= factor * a[pivot*n+col];
            b[row] -= factor * b[pivot];
        }
    }
    for (row = n; row > 0; --row) {
        size_t i = row - 1; double sum = b[i];
        for (col = i + 1; col < n; ++col) sum -= a[i*n+col] * solution[col];
        solution[i] = sum / a[i*n+i];
    }
    free(a); free(b); return 1;
}
int main(void) {
    const double a[] = {3,2,-1, 2,-2,4, -1,0.5,-1};
    const double b[] = {1,-2,0};
    double x[3] = {0,0,0}; int ok = num_solve_linear(a,b,3,x);
    printf("success = %d\nx1 = %.8f\nx2 = %.8f\nx3 = %.8f\n", ok,x[0],x[1],x[2]);
    return ok ? EXIT_SUCCESS : EXIT_FAILURE;
}
