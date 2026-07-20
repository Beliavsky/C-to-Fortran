#include <stdio.h>

void swap_int(int *a, int *b) {
    int temporary = *a;
    *a = *b;
    *b = temporary;
}

int main(void) {
    int x = 10;
    int y = 20;

    swap_int(&x, &y);
    printf("%d %d\n", x, y);

    return 0;
}
