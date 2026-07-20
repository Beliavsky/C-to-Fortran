#include <stdio.h>

void add_arrays(
    const double *restrict a,
    const double *restrict b,
    double *restrict c,
    int n
) {
    int i;

    for (i = 0; i < n; ++i) {
        c[i] = a[i] + b[i];
    }
}

int main(void) {
    double a[] = {1, 2, 3};
    double b[] = {4, 5, 6};
    double c[3];
    int i;

    add_arrays(a, b, c, 3);

    for (i = 0; i < 3; ++i) {
        printf("%.1f\n", c[i]);
    }

    return 0;
}
