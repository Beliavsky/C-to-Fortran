#include <stdio.h>

int main(void) {
    int i;
    int j;

    for (i = 1; i <= 3; ++i) {
        for (j = 1; j <= 4; ++j) {
            printf("%d %d %d\n", i, j, i * j);
        }
    }

    return 0;
}
