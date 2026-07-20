#include <stdio.h>

int next_value(void) {
    static int value = 0;
    value += 2;
    return value;
}

int main(void) {
    printf("%d\n", next_value());
    printf("%d\n", next_value());
    printf("%d\n", next_value());

    return 0;
}
