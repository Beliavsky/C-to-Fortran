#include <stdio.h>

void insertion_sort(double x[], int n) {
    int i;

    for (i = 1; i < n; ++i) {
        double key = x[i];
        int j = i - 1;

        while (j >= 0 && x[j] > key) {
            x[j + 1] = x[j];
            --j;
        }

        x[j + 1] = key;
    }
}

int main(void) {
    double x[] = {3.2, -1.0, 7.5, 2.2, 0.0};
    int i;

    insertion_sort(x, 5);

    for (i = 0; i < 5; ++i) {
        printf("%.2f\n", x[i]);
    }

    return 0;
}
