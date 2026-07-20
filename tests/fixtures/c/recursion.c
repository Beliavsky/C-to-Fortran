#include <stdio.h>

long long fibonacci(int n) {
    if (n <= 1) {
        return n;
    }
    return fibonacci(n - 1) + fibonacci(n - 2);
}

int main(void) {
    printf("%lld\n", fibonacci(12));
    return 0;
}
