#include <stdio.h>
#include <stdlib.h>

/* Evaluate a polynomial using Horner's method. */
static double num_polynomial(const double coefficients[], size_t n, double x) {
    double result; size_t i;
    if (n == 0) return 0.0;
    result = coefficients[n - 1];
    for (i = n - 1; i > 0; --i) result = result * x + coefficients[i - 1];
    return result;
}

/* Test polynomial evaluation. */
int main(void) {
    const double c[] = {1, -2, 0, 3};
    printf("value = %.8f\n", num_polynomial(c, 4, 2));
    return EXIT_SUCCESS;
}
