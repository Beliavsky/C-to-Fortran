#include <stdio.h>

int main(void) {
    int x = 5;
    int y = 12;

    if (x > 0 && y > 0) {
        printf("both positive\n");
    }

    if (x == 5 || y == 5) {
        printf("at least one is five\n");
    }

    if (!(x > y)) {
        printf("x is not greater than y\n");
    }

    return 0;
}
