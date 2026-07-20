#include <complex.h>
#include <stdio.h>

int main(void) {
    double complex z = 2.0 + 3.0 * I;
    double complex w = 1.0 - 4.0 * I;
    double complex product = z * w;
    printf("%.2f %.2f\n", creal(product), cimag(product));
    return 0;
}
