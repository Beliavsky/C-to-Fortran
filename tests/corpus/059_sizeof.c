#include <stdio.h>

int main(void) {
    int x[12];

    printf("int bytes = %zu\n", sizeof(int));
    printf("double bytes = %zu\n", sizeof(double));
    printf("array bytes = %zu\n", sizeof(x));
    printf("elements = %zu\n", sizeof(x) / sizeof(x[0]));

    return 0;
}
