#include <limits.h>
#include <stdio.h>

int main(void) {
    unsigned int x = UINT_MAX;

    printf("%u\n", x);
    x += 1U;
    printf("%u\n", x);

    return 0;
}
