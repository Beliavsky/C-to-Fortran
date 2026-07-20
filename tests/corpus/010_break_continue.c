#include <stdio.h>

int main(void) {
    int i;

    for (i = 0; i < 10; ++i) {
        if (i == 3) {
            continue;
        }
        if (i == 8) {
            break;
        }
        printf("%d\n", i);
    }

    return 0;
}
