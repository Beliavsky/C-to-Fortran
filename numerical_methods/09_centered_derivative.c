#include <math.h>
#include <stdio.h>
#include <stdlib.h>

typedef double (*num_function)(double);

/* Approximate a derivative using a centered difference. */
static double num_derivative(num_function f, double x, double h) {
    if (f == NULL || h <= 0.0) return NAN;
    return (f(x + h) - f(x - h)) / (2.0 * h);
}

/* Return sine of x. */
static double test_function(double x) { return sin(x); }

/* Test centered numerical differentiation. */
int main(void) {
    double x = 1.0;
    printf("estimate = %.10f\n", num_derivative(test_function, x, 1e-5));
    printf("exact    = %.10f\n", cos(x));
    return EXIT_SUCCESS;
}
