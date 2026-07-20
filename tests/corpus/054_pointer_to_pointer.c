#include <stdio.h>

void set_value(int **p, int *target) {
    *p = target;
}

int main(void) {
    int x = 77;
    int *p = NULL;

    set_value(&p, &x);
    printf("%d\n", *p);

    return 0;
}
