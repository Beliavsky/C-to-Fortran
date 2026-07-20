#include <stdio.h>

double circle_area(const double radius) {
    const double pi = 3.141592653589793;
    return pi * radius * radius;
}

int main(void) {
    printf("%.6f\n", circle_area(2.0));
    return 0;
}
