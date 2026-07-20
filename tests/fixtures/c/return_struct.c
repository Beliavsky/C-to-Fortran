#include <stdio.h>

struct pair {
    int first;
    int second;
};

struct pair divide_ints(int a, int b) {
    struct pair result = {a / b, a % b};
    return result;
}

int main(void) {
    struct pair result = divide_ints(17, 5);
    printf("%d\n", result.first);
    printf("%d\n", result.second);
    return 0;
}
