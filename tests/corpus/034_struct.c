#include <stdio.h>

struct point {
    double x;
    double y;
};

int main(void) {
    struct point p = {2.5, -1.0};

    printf("%.2f %.2f\n", p.x, p.y);
    return 0;
}
