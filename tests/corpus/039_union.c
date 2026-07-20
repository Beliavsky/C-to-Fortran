#include <stdio.h>

union number {
    int i;
    float f;
};

int main(void) {
    union number value;

    value.i = 123;
    printf("%d\n", value.i);

    value.f = 4.5f;
    printf("%.2f\n", value.f);

    return 0;
}
