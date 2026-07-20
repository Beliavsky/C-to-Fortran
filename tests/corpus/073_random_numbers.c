#include <stdio.h>
#include <stdlib.h>

int main(void) {
    int i;

    srand(12345U);

    for (i = 0; i < 10; ++i) {
        printf("%d\n", rand());
    }

    return 0;
}
