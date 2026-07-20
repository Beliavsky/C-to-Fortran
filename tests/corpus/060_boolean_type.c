#include <stdbool.h>
#include <stdio.h>

bool is_even(int x) {
    return x % 2 == 0;
}

int main(void) {
    int i;

    for (i = 0; i < 6; ++i) {
        printf("%d %s\n", i, is_even(i) ? "true" : "false");
    }

    return 0;
}
