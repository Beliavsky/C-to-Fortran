#include <stdio.h>

struct counter {
    int value;
};

void increment(struct counter *c) {
    c->value += 1;
}

int main(void) {
    struct counter c = {10};

    increment(&c);
    printf("%d\n", c.value);

    return 0;
}
