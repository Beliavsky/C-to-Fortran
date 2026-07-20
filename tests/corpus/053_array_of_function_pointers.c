#include <stdio.h>

int add(int a, int b) {
    return a + b;
}

int subtract(int a, int b) {
    return a - b;
}

int multiply(int a, int b) {
    return a * b;
}

int main(void) {
    int (*operations[3])(int, int) = {add, subtract, multiply};
    int i;

    for (i = 0; i < 3; ++i) {
        printf("%d\n", operations[i](8, 3));
    }

    return 0;
}
