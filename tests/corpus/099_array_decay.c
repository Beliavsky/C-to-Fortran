#include <stdio.h>

void print_first(const int *x) {
    printf("%d\n", x[0]);
}

int main(void) {
    int x[3] = {11, 22, 33};

    print_first(x);
    print_first(&x[0]);

    return 0;
}
