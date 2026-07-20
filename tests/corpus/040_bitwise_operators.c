#include <stdio.h>

int main(void) {
    unsigned int a = 12U;
    unsigned int b = 10U;

    printf("%u\n", a & b);
    printf("%u\n", a | b);
    printf("%u\n", a ^ b);
    printf("%u\n", a << 1);
    printf("%u\n", b >> 1);

    return 0;
}
