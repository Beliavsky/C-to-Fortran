#include <stdio.h>

struct configuration {
    int iterations;
    double tolerance;
    int verbose;
};

int main(void) {
    struct configuration config = {
        .tolerance = 1.0e-6,
        .iterations = 100,
        .verbose = 1
    };

    printf("%d %.8f %d\n",
           config.iterations,
           config.tolerance,
           config.verbose);

    return 0;
}
