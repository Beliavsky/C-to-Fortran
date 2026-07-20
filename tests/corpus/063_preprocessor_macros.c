#include <stdio.h>

#define SQUARE(x) ((x) * (x))
#define MAXIMUM(a, b) ((a) > (b) ? (a) : (b))

int main(void) {
    int x = 4;
    int y = 7;

    printf("%d\n", SQUARE(x));
    printf("%d\n", MAXIMUM(x, y));

    return 0;
}
