#include <stdio.h>

int main(void) {
    const char *names[] = {"alpha", "beta", "gamma", "delta"};
    int i;

    for (i = 0; i < 4; ++i) {
        printf("%s\n", names[i]);
    }

    return 0;
}
