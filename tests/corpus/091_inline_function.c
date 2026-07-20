#include <stdio.h>

static inline double square(double x) {
    return x * x;
}

int main(void) {
    printf("%.2f\n", square(4.5));
    return 0;
}
