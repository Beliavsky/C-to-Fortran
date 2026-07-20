#include <stdio.h>

int main(void) {
    volatile int flag = 1;
    int count = 0;

    while (flag && count < 3) {
        printf("%d\n", count);
        ++count;
    }

    return 0;
}
