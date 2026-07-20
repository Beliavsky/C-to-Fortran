#include <stdio.h>

double evaluate_polynomial(const double coefficients[], int degree, double x) {
    int i;
    double result = coefficients[degree];

    for (i = degree - 1; i >= 0; --i) {
        result = result * x + coefficients[i];
    }

    return result;
}

int main(void) {
    double coefficients[] = {1.0, -2.0, 0.5, 3.0};

    printf("%.6f\n", evaluate_polynomial(coefficients, 3, 2.0));
    return 0;
}
