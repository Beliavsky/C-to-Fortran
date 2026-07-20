#include <stdio.h>

void min_max(const int x[], int n, int *minimum, int *maximum) {
    int i;

    *minimum = x[0];
    *maximum = x[0];

    for (i = 1; i < n; ++i) {
        if (x[i] < *minimum) {
            *minimum = x[i];
        }
        if (x[i] > *maximum) {
            *maximum = x[i];
        }
    }
}

int main(void) {
    int x[] = {9, -2, 14, 7, 0, 3};
    int minimum;
    int maximum;

    min_max(x, 6, &minimum, &maximum);
    printf("min = %d\n", minimum);
    printf("max = %d\n", maximum);

    return 0;
}
