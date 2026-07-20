#include <stdio.h>

#define M 2
#define K 3
#define N 2

int main(void) {
    double a[M][K] = {{1, 2, 3}, {4, 5, 6}};
    double b[K][N] = {{7, 8}, {9, 10}, {11, 12}};
    double c[M][N] = {{0}};
    int i;
    int j;
    int k;

    for (i = 0; i < M; ++i) {
        for (j = 0; j < N; ++j) {
            for (k = 0; k < K; ++k) {
                c[i][j] += a[i][k] * b[k][j];
            }
        }
    }

    for (i = 0; i < M; ++i) {
        for (j = 0; j < N; ++j) {
            printf("%.1f%c", c[i][j], j == N - 1 ? '\n' : ' ');
        }
    }

    return 0;
}
