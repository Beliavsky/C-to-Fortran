#include <stdio.h>

#define ROWS 2
#define COLS 3

void matrix_add(
    const double a[ROWS][COLS],
    const double b[ROWS][COLS],
    double c[ROWS][COLS]
) {
    int i;
    int j;

    for (i = 0; i < ROWS; ++i) {
        for (j = 0; j < COLS; ++j) {
            c[i][j] = a[i][j] + b[i][j];
        }
    }
}

int main(void) {
    double a[ROWS][COLS] = {{1, 2, 3}, {4, 5, 6}};
    double b[ROWS][COLS] = {{6, 5, 4}, {3, 2, 1}};
    double c[ROWS][COLS];
    int i;
    int j;

    matrix_add(a, b, c);

    for (i = 0; i < ROWS; ++i) {
        for (j = 0; j < COLS; ++j) {
            printf("%.1f%c", c[i][j], j == COLS - 1 ? '\n' : ' ');
        }
    }

    return 0;
}
