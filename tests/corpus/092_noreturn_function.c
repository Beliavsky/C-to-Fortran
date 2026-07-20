#include <stdio.h>
#include <stdlib.h>

_Noreturn void fail(const char *message) {
    fprintf(stderr, "%s\n", message);
    exit(EXIT_FAILURE);
}

int main(void) {
    int ok = 1;

    if (!ok) {
        fail("failure");
    }

    printf("success\n");
    return 0;
}
