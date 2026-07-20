#include <stdio.h>

void mean_variance(
    const double x[],
    int n,
    double *mean,
    double *variance
) {
    int i;
    double sum = 0.0;
    double sumsq = 0.0;

    for (i = 0; i < n; ++i) {
        sum += x[i];
        sumsq += x[i] * x[i];
    }

    *mean = sum / n;
    *variance = (sumsq - n * (*mean) * (*mean)) / (n - 1);
}

int main(void) {
    double x[] = {1, 2, 3, 4, 5};
    double mean;
    double variance;

    mean_variance(x, 5, &mean, &variance);

    printf("%.6f %.6f\n", mean, variance);
    return 0;
}
