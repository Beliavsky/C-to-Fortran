#include <stdio.h>

int main(void) {
    int i = 0;

start:
    if (i >= 5) {
        goto done;
    }

    printf("%d\n", i);
    ++i;
    goto start;

done:
    return 0;
}
