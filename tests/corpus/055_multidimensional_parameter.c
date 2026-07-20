#include <stdio.h>

#define COLS 3

double matrix_sum(const double a[][COLS], int rows) {
    int i;
    int j;
    double sum = 0.0;

    for (i = 0; i < rows; ++i) {
        for (j = 0; j < COLS; ++j) {
            sum += a[i][j];
        }
    }

    return sum;
}

int main(void) {
    double a[2][COLS] = {{1, 2, 3}, {4, 5, 6}};

    printf("%.2f\n", matrix_sum(a, 2));
    return 0;
}
