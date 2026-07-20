#include <stdio.h>

struct quotient_remainder {
    int quotient;
    int remainder;
};

struct quotient_remainder divide_ints(int a, int b) {
    struct quotient_remainder result = {a / b, a % b};
    return result;
}

int main(void) {
    struct quotient_remainder result = divide_ints(17, 5);

    printf("%d %d\n", result.quotient, result.remainder);
    return 0;
}
