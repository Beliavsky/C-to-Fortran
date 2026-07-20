#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#define PI 3.14159265358979323846
typedef double (*num_function)(double);

/* Integrate a function using the trapezoidal rule. */
static double num_integrate_trapezoid(num_function f, double a, double b, size_t n) {
    double h, sum; size_t i;
    if (f == NULL || n == 0) return NAN;
    h = (b - a) / n; sum = 0.5 * (f(a) + f(b));
    for (i = 1; i < n; ++i) sum += f(a + i * h);
    return h * sum;
}
static double test_function(double x) { return sin(x); }
int main(void) {
    printf("integral = %.10f\n", num_integrate_trapezoid(test_function, 0, PI, 10000));
    printf("exact    = %.10f\n", 2.0);
    return EXIT_SUCCESS;
}
