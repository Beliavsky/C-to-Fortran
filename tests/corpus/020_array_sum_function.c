#include <stdio.h>

double array_sum(const double x[], int n) {
    int i;
    double sum = 0.0;

    for (i = 0; i < n; ++i) {
        sum += x[i];
    }

    return sum;
}

int main(void) {
    double x[] = {1.5, 2.5, 3.5, 4.5};
    int n = (int)(sizeof(x) / sizeof(x[0]));

    printf("%.3f\n", array_sum(x, n));
    return 0;
}
