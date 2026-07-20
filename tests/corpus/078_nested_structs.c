#include <stdio.h>

struct point {
    double x;
    double y;
};

struct rectangle {
    struct point lower_left;
    struct point upper_right;
};

double rectangle_area(struct rectangle r) {
    return (r.upper_right.x - r.lower_left.x) *
           (r.upper_right.y - r.lower_left.y);
}

int main(void) {
    struct rectangle r = {{1.0, 2.0}, {6.0, 8.0}};

    printf("%.2f\n", rectangle_area(r));
    return 0;
}
