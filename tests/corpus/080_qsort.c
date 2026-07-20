#include <stdio.h>
#include <stdlib.h>

int compare_ints(const void *a, const void *b) {
    int x = *(const int *)a;
    int y = *(const int *)b;

    return (x > y) - (x < y);
}

int main(void) {
    int x[] = {7, 1, 9, 3, 5};
    int i;

    qsort(x, 5, sizeof(x[0]), compare_ints);

    for (i = 0; i < 5; ++i) {
        printf("%d\n", x[i]);
    }

    return 0;
}
