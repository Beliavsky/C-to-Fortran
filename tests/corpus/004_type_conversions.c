#include <stdio.h>

int main(void) {
    int n = 7;
    double x = 2.5;
    double y = n * x;
    int z = (int)y;

    printf("y = %.2f\n", y);
    printf("z = %d\n", z);

    return 0;
}
