#include <stdio.h>

int main(void) {
    int x = 5;
    int a = x++;
    int b = ++x;
    int c = x--;
    int d = --x;

    printf("%d %d %d %d %d\n", x, a, b, c, d);
    return 0;
}
