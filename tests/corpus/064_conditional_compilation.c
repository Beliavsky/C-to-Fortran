#include <stdio.h>

#define USE_DOUBLE 1

int main(void) {
#if USE_DOUBLE
    double x = 1.25;
    printf("%.2f\n", x);
#else
    int x = 1;
    printf("%d\n", x);
#endif

    return 0;
}
