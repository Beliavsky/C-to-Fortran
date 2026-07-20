#include <stdio.h>

int increment(int *x) {
    ++(*x);
    return *x;
}

int main(void) {
    int x = 0;

    if (0 && increment(&x)) {
        printf("unreachable\n");
    }

    printf("%d\n", x);

    if (1 || increment(&x)) {
        printf("%d\n", x);
    }

    return 0;
}
