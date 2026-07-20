#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#define NUM_TOL 1.0e-14
typedef double (*num_function)(double);

/* Find a root using Newton's method. */
static int num_newton(num_function f, num_function df, double x, double tol, int maxit, double *root) {
    int iter;
    if (f == NULL || df == NULL || root == NULL || tol <= 0 || maxit <= 0) return 0;
    for (iter = 0; iter < maxit; ++iter) {
        double fx = f(x), dfx = df(x), next;
        if (fabs(fx) < tol) { *root = x; return 1; }
        if (fabs(dfx) < NUM_TOL) return 0;
        next = x - fx / dfx;
        if (fabs(next - x) < tol) { *root = next; return 1; }
        x = next;
    }
    *root = x; return 0;
}
static double f(double x) { return x * x - 2.0; }
static double df(double x) { return 2.0 * x; }
int main(void) {
    double root; int ok = num_newton(f, df, 1.0, 1e-12, 100, &root);
    printf("success = %d\nroot = %.12f\nexact = %.12f\n", ok, root, sqrt(2.0));
    return ok ? EXIT_SUCCESS : EXIT_FAILURE;
}
