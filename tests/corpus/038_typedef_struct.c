#include <stdio.h>

typedef struct {
    double real;
    double imag;
} complex_number;

complex_number add_complex(complex_number a, complex_number b) {
    complex_number result;

    result.real = a.real + b.real;
    result.imag = a.imag + b.imag;

    return result;
}

int main(void) {
    complex_number a = {1.0, 2.0};
    complex_number b = {3.0, -4.0};
    complex_number c = add_complex(a, b);

    printf("%.2f %.2f\n", c.real, c.imag);
    return 0;
}
