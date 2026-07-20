#include <stdio.h>

struct point {
    double x;
    double y;
};

double squared_norm(struct point p) {
    return p.x * p.x + p.y * p.y;
}

int main(void) {
    printf("%.2f\n", squared_norm((struct point){3.0, 4.0}));
    return 0;
}
