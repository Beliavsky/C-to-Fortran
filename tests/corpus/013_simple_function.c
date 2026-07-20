#include <stdio.h>

int square(int x) {
    return x * x;
}

int main(void) {
    int value = 7;
    printf("%d\n", square(value));
    return 0;
}
