#include <math.h>
#include <stdio.h>

double function(double x) {
    return exp(-x * x);
}

double trapezoidal(double a, double b, int n) {
    int i;
    double h = (b - a) / n;
    double sum = 0.5 * (function(a) + function(b));

    for (i = 1; i < n; ++i) {
        sum += function(a + i * h);
    }

    return h * sum;
}

int main(void) {
    printf("%.10f\n", trapezoidal(0.0, 1.0, 10000));
    return 0;
}
