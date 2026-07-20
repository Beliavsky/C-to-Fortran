#include <stdio.h>

int main(void) {
    int values[6] = {4, 8, 15, 16, 23, 42};
    int i;

    for (i = 0; i < 6; ++i) {
        printf("%d\n", values[i]);
    }

    return 0;
}
