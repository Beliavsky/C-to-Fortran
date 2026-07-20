#include <stdio.h>

double sum_values(int n, const double x[n]) {
    int i;
    double sum = 0.0;

    for (i = 0; i < n; ++i) {
        sum += x[i];
    }

    return sum;
}

int main(void) {
    int n = 5;
    double x[n];
    int i;

    for (i = 0; i < n; ++i) {
        x[i] = i + 0.25;
    }

    printf("%.2f\n", sum_values(n, x));
    return 0;
}
