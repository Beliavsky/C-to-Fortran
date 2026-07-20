#include <stdio.h>

struct point {
    double x;
    double y;
};

double squared_distance(struct point a, struct point b) {
    double dx = a.x - b.x;
    double dy = a.y - b.y;

    return dx * dx + dy * dy;
}

int main(void) {
    struct point a = {1.0, 2.0};
    struct point b = {4.0, 6.0};

    printf("%.2f\n", squared_distance(a, b));
    return 0;
}
