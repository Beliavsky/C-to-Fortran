#include <math.h>
#include <stdio.h>
#include <stdlib.h>
typedef double (*num_function)(double);

/* Find a root using the bisection method. */
static int num_bisection(num_function f, double a, double b, double tol, int maxit, double *root) {
    double fa, fb; int iter;
    if (f == NULL || root == NULL || tol <= 0 || maxit <= 0) return 0;
    fa = f(a); fb = f(b);
    if (fa * fb > 0) return 0;
    for (iter = 0; iter < maxit; ++iter) {
        double m = 0.5 * (a + b), fm = f(m);
        if (fabs(fm) < tol || 0.5 * fabs(b - a) < tol) { *root = m; return 1; }
        if (fa * fm <= 0) { b = m; fb = fm; } else { a = m; fa = fm; }
    }
    *root = 0.5 * (a + b); return 0;
}
static double test_function(double x) { return x * x - 2.0; }
int main(void) {
    double root; int ok = num_bisection(test_function, 0, 2, 1e-12, 1000, &root);
    printf("success = %d\nroot = %.12f\nexact = %.12f\n", ok, root, sqrt(2.0));
    return ok ? EXIT_SUCCESS : EXIT_FAILURE;
}
