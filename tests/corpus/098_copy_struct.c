#include <stdio.h>

struct pair {
    int first;
    int second;
};

int main(void) {
    struct pair a = {3, 7};
    struct pair b = a;

    b.first = 10;

    printf("%d %d\n", a.first, a.second);
    printf("%d %d\n", b.first, b.second);

    return 0;
}
