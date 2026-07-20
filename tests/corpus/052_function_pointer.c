#include <stdio.h>

double square(double x) {
    return x * x;
}

double cube(double x) {
    return x * x * x;
}

double apply(double (*function)(double), double x) {
    return function(x);
}

int main(void) {
    printf("%.2f\n", apply(square, 3.0));
    printf("%.2f\n", apply(cube, 3.0));

    return 0;
}
