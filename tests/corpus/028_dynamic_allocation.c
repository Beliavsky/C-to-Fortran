#include <stdio.h>
#include <stdlib.h>

int main(void) {
    int n = 8;
    double *x = malloc((size_t)n * sizeof(*x));
    int i;

    if (x == NULL) {
        return 1;
    }

    for (i = 0; i < n; ++i) {
        x[i] = 0.5 * i;
    }

    for (i = 0; i < n; ++i) {
        printf("%.2f\n", x[i]);
    }

    free(x);
    return 0;
}
