#include <stdio.h>

int maximum(int a, int b);

int main(void) {
    printf("%d\n", maximum(12, 9));
    return 0;
}

int maximum(int a, int b) {
    return a > b ? a : b;
}
