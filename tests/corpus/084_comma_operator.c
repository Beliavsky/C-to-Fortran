#include <stdio.h>

int main(void) {
    int x;
    int y;

    x = (y = 3, y + 4);

    printf("%d %d\n", x, y);
    return 0;
}
