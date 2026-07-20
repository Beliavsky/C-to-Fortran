#include <stdio.h>
#include <stdlib.h>

int main(void) {
    int i;
    int n = 4;
    int *x = calloc((size_t)n, sizeof(*x));

    if (x == NULL) {
        return 1;
    }

    for (i = 0; i < n; ++i) {
        x[i] = i + 1;
    }

    n = 8;
    {
        int *temporary = realloc(x, (size_t)n * sizeof(*x));

        if (temporary == NULL) {
            free(x);
            return 1;
        }

        x = temporary;
    }

    for (i = 4; i < n; ++i) {
        x[i] = i + 1;
    }

    for (i = 0; i < n; ++i) {
        printf("%d\n", x[i]);
    }

    free(x);
    return 0;
}
