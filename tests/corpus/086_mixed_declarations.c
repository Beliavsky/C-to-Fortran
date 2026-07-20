#include <stdio.h>

int main(void) {
    int x = 3;

    printf("%d\n", x);

    {
        double y = 2.5;
        printf("%.2f\n", y);
    }

    x += 4;
    printf("%d\n", x);

    return 0;
}
