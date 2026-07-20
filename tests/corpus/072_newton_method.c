#include <math.h>
#include <stdio.h>

double f(double x) {
    return x * x - 2.0;
}

double df(double x) {
    return 2.0 * x;
}

int main(void) {
    double x = 1.0;
    int iteration;

    for (iteration = 0; iteration < 10; ++iteration) {
        x -= f(x) / df(x);
    }

    printf("%.12f\n", x);
    printf("%.12f\n", sqrt(2.0));

    return 0;
}
