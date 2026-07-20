#include <stdio.h>

long long fibonacci(int n) {
    if (n <= 1) {
        return n;
    }

    return fibonacci(n - 1) + fibonacci(n - 2);
}

int main(void) {
    int i;

    for (i = 0; i <= 12; ++i) {
        printf("%d %lld\n", i, fibonacci(i));
    }

    return 0;
}
