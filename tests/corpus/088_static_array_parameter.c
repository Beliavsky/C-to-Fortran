#include <stdio.h>

double dot_product(
    int n,
    const double a[static 1],
    const double b[static 1]
) {
    int i;
    double result = 0.0;

    for (i = 0; i < n; ++i) {
        result += a[i] * b[i];
    }

    return result;
}

int main(void) {
    double a[] = {1, 2, 3};
    double b[] = {4, 5, 6};

    printf("%.2f\n", dot_product(3, a, b));
    return 0;
}
