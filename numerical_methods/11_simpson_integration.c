#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#define PI 3.14159265358979323846
typedef double (*num_function)(double);

/* Integrate a function using Simpson's rule. */
static double num_integrate_simpson(num_function f, double a, double b, size_t n) {
    double h, sum; size_t i;
    if (f == NULL || n == 0 || n % 2 != 0) return NAN;
    h = (b - a) / n; sum = f(a) + f(b);
    for (i = 1; i < n; ++i) sum += (i % 2 == 0 ? 2.0 : 4.0) * f(a + i * h);
    return h * sum / 3.0;
}
static double test_function(double x) { return sin(x); }
int main(void) {
    printf("integral = %.10f\n", num_integrate_simpson(test_function, 0, PI, 1000));
    printf("exact    = %.10f\n", 2.0);
    return EXIT_SUCCESS;
}
