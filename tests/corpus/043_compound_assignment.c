#include <stdio.h>

int main(void) {
    int x = 10;

    x += 5;
    x *= 2;
    x -= 4;
    x /= 2;
    x %= 7;

    printf("%d\n", x);
    return 0;
}
