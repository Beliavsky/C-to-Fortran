#include <stdio.h>

struct observation {
    double x;
    double y;
};

int main(void) {
    struct observation data[3] = {
        {1.0, 2.0},
        {2.0, 4.5},
        {3.0, 5.8}
    };
    int i;

    for (i = 0; i < 3; ++i) {
        printf("%.2f %.2f\n", data[i].x, data[i].y);
    }

    return 0;
}
