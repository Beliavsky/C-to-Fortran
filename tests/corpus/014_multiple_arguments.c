#include <stdio.h>

double weighted_sum(double x, double y, double a, double b) {
    return a * x + b * y;
}

int main(void) {
    printf("%.3f\n", weighted_sum(2.0, 3.0, 0.25, 0.75));
    return 0;
}
