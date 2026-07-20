#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#define PI 3.14159265358979323846
#define NUM_TOL 1.0e-12
#define NUM_MAX_ITER 1000

typedef double (*num_function)(double);

/* Return the sum of an array. */
double num_sum(const double x[], size_t n) {
    double sum = 0.0;
    size_t i;

    for (i = 0; i < n; ++i) {
        sum += x[i];
    }

    return sum;
}

/* Return the arithmetic mean of an array. */
double num_mean(const double x[], size_t n) {
    if (n == 0) {
        return NAN;
    }

    return num_sum(x, n) / n;
}

/* Return the minimum value in an array. */
double num_min(const double x[], size_t n) {
    double minimum;
    size_t i;

    if (n == 0) {
        return NAN;
    }

    minimum = x[0];

    for (i = 1; i < n; ++i) {
        if (x[i] < minimum) {
            minimum = x[i];
        }
    }

    return minimum;
}

/* Return the maximum value in an array. */
double num_max(const double x[], size_t n) {
    double maximum;
    size_t i;

    if (n == 0) {
        return NAN;
    }

    maximum = x[0];

    for (i = 1; i < n; ++i) {
        if (x[i] > maximum) {
            maximum = x[i];
        }
    }

    return maximum;
}

/* Return the sample variance of an array. */
double num_variance(const double x[], size_t n) {
    double mean;
    double sumsq = 0.0;
    size_t i;

    if (n < 2) {
        return NAN;
    }

    mean = num_mean(x, n);

    for (i = 0; i < n; ++i) {
        double difference = x[i] - mean;
        sumsq += difference * difference;
    }

    return sumsq / (n - 1);
}

/* Return the sample standard deviation of an array. */
double num_sd(const double x[], size_t n) {
    return sqrt(num_variance(x, n));
}

/* Return the dot product of two arrays. */
double num_dot(
    const double x[],
    const double y[],
    size_t n
) {
    double result = 0.0;
    size_t i;

    for (i = 0; i < n; ++i) {
        result += x[i] * y[i];
    }

    return result;
}

/* Return the Euclidean norm of an array. */
double num_norm(const double x[], size_t n) {
    return sqrt(num_dot(x, x, n));
}

/* Fill an array with equally spaced values. */
int num_linspace(
    double start,
    double end,
    size_t n,
    double result[]
) {
    double step;
    size_t i;

    if (n == 0) {
        return 0;
    }

    if (n == 1) {
        result[0] = start;
        return 1;
    }

    step = (end - start) / (n - 1);

    for (i = 0; i < n; ++i) {
        result[i] = start + i * step;
    }

    result[n - 1] = end;

    return 1;
}

/* Evaluate a polynomial using Horner's method. */
double num_polynomial(
    const double coefficients[],
    size_t n,
    double x
) {
    double result;
    size_t i;

    if (n == 0) {
        return 0.0;
    }

    result = coefficients[n - 1];

    for (i = n - 1; i > 0; --i) {
        result =
            result * x +
            coefficients[i - 1];
    }

    return result;
}

/* Approximate a derivative using a centered difference. */
double num_derivative(
    num_function function,
    double x,
    double step
) {
    if (step <= 0.0) {
        return NAN;
    }

    return (
        function(x + step) -
        function(x - step)
    ) / (2.0 * step);
}

/* Integrate a function using the trapezoidal rule. */
double num_integrate_trapezoid(
    num_function function,
    double lower,
    double upper,
    size_t intervals
) {
    double step;
    double sum;
    size_t i;

    if (intervals == 0) {
        return NAN;
    }

    step = (upper - lower) / intervals;

    sum =
        0.5 *
        (
            function(lower) +
            function(upper)
        );

    for (i = 1; i < intervals; ++i) {
        sum += function(lower + i * step);
    }

    return step * sum;
}

/* Integrate a function using Simpson's rule. */
double num_integrate_simpson(
    num_function function,
    double lower,
    double upper,
    size_t intervals
) {
    double step;
    double sum;
    size_t i;

    if (intervals == 0 || intervals % 2 != 0) {
        return NAN;
    }

    step = (upper - lower) / intervals;
    sum = function(lower) + function(upper);

    for (i = 1; i < intervals; ++i) {
        double weight = i % 2 == 0 ? 2.0 : 4.0;
        sum += weight * function(lower + i * step);
    }

    return step * sum / 3.0;
}

/* Find a root using the bisection method. */
int num_bisection(
    num_function function,
    double lower,
    double upper,
    double tolerance,
    int max_iterations,
    double *root
) {
    double f_lower;
    double f_upper;
    int iteration;

    if (
        root == NULL ||
        tolerance <= 0.0 ||
        max_iterations <= 0
    ) {
        return 0;
    }

    f_lower = function(lower);
    f_upper = function(upper);

    if (f_lower == 0.0) {
        *root = lower;
        return 1;
    }

    if (f_upper == 0.0) {
        *root = upper;
        return 1;
    }

    if (f_lower * f_upper > 0.0) {
        return 0;
    }

    for (
        iteration = 0;
        iteration < max_iterations;
        ++iteration
    ) {
        double middle = 0.5 * (lower + upper);
        double f_middle = function(middle);

        if (
            fabs(f_middle) < tolerance ||
            0.5 * fabs(upper - lower) < tolerance
        ) {
            *root = middle;
            return 1;
        }

        if (f_lower * f_middle <= 0.0) {
            upper = middle;
            f_upper = f_middle;
        } else {
            lower = middle;
            f_lower = f_middle;
        }
    }

    *root = 0.5 * (lower + upper);
    return 0;
}

/* Find a root using Newton's method. */
int num_newton(
    num_function function,
    num_function derivative,
    double initial,
    double tolerance,
    int max_iterations,
    double *root
) {
    double x = initial;
    int iteration;

    if (
        root == NULL ||
        tolerance <= 0.0 ||
        max_iterations <= 0
    ) {
        return 0;
    }

    for (
        iteration = 0;
        iteration < max_iterations;
        ++iteration
    ) {
        double fx = function(x);
        double dfx = derivative(x);
        double next;

        if (fabs(fx) < tolerance) {
            *root = x;
            return 1;
        }

        if (fabs(dfx) < NUM_TOL) {
            return 0;
        }

        next = x - fx / dfx;

        if (fabs(next - x) < tolerance) {
            *root = next;
            return 1;
        }

        x = next;
    }

    *root = x;
    return 0;
}

/* Solve a dense linear system using Gaussian elimination. */
int num_solve_linear(
    const double matrix[],
    const double right_hand_side[],
    size_t n,
    double solution[]
) {
    double *a;
    double *b;
    size_t pivot;
    size_t row;
    size_t column;

    if (
        matrix == NULL ||
        right_hand_side == NULL ||
        solution == NULL ||
        n == 0
    ) {
        return 0;
    }

    a = malloc(n * n * sizeof(*a));
    b = malloc(n * sizeof(*b));

    if (a == NULL || b == NULL) {
        free(a);
        free(b);
        return 0;
    }

    for (row = 0; row < n; ++row) {
        b[row] = right_hand_side[row];

        for (column = 0; column < n; ++column) {
            a[row * n + column] =
                matrix[row * n + column];
        }
    }

    for (pivot = 0; pivot < n; ++pivot) {
        size_t best_row = pivot;
        double best_value =
            fabs(a[pivot * n + pivot]);

        for (row = pivot + 1; row < n; ++row) {
            double value =
                fabs(a[row * n + pivot]);

            if (value > best_value) {
                best_value = value;
                best_row = row;
            }
        }

        if (best_value < NUM_TOL) {
            free(a);
            free(b);
            return 0;
        }

        if (best_row != pivot) {
            for (column = 0; column < n; ++column) {
                double temporary =
                    a[pivot * n + column];

                a[pivot * n + column] =
                    a[best_row * n + column];

                a[best_row * n + column] =
                    temporary;
            }

            {
                double temporary = b[pivot];
                b[pivot] = b[best_row];
                b[best_row] = temporary;
            }
        }

        for (row = pivot + 1; row < n; ++row) {
            double factor =
                a[row * n + pivot] /
                a[pivot * n + pivot];

            a[row * n + pivot] = 0.0;

            for (
                column = pivot + 1;
                column < n;
                ++column
            ) {
                a[row * n + column] -=
                    factor *
                    a[pivot * n + column];
            }

            b[row] -= factor * b[pivot];
        }
    }

    for (row = n; row > 0; --row) {
        size_t i = row - 1;
        double sum = b[i];

        for (column = i + 1; column < n; ++column) {
            sum -=
                a[i * n + column] *
                solution[column];
        }

        solution[i] =
            sum / a[i * n + i];
    }

    free(a);
    free(b);

    return 1;
}

/* Print an array on one line. */
void num_print_vector(
    const double x[],
    size_t n
) {
    size_t i;

    printf("[");

    for (i = 0; i < n; ++i) {
        printf("%.8f", x[i]);

        if (i + 1 < n) {
            printf(", ");
        }
    }

    printf("]\n");
}

/* Return x squared minus two. */
static double root_function(double x) {
    return x * x - 2.0;
}

/* Return the derivative of x squared minus two. */
static double root_derivative(double x) {
    return 2.0 * x;
}

/* Return sine of x. */
static double sine_function(double x) {
    return sin(x);
}

/* Run basic tests of the numerical library. */
int main(void) {
    const double x[] = {
        1.0,
        2.0,
        3.0,
        4.0,
        5.0
    };

    const double y[] = {
        5.0,
        4.0,
        3.0,
        2.0,
        1.0
    };

    const double coefficients[] = {
        1.0,
        -2.0,
        0.0,
        3.0
    };

    const double matrix[] = {
         3.0,  2.0, -1.0,
         2.0, -2.0,  4.0,
        -1.0,  0.5, -1.0
    };

    const double right_hand_side[] = {
         1.0,
        -2.0,
         0.0
    };

    double grid[6];
    double solution[3] = {0.0, 0.0, 0.0};
    double root;
    int success;

    printf("array statistics\n");
    printf("sum      = %.8f\n", num_sum(x, 5));
    printf("mean     = %.8f\n", num_mean(x, 5));
    printf("min      = %.8f\n", num_min(x, 5));
    printf("max      = %.8f\n", num_max(x, 5));
    printf("variance = %.8f\n", num_variance(x, 5));
    printf("sd       = %.8f\n", num_sd(x, 5));
    printf("dot      = %.8f\n", num_dot(x, y, 5));
    printf("norm     = %.8f\n\n", num_norm(x, 5));

    printf("linspace\n");
    num_linspace(0.0, 1.0, 6, grid);
    num_print_vector(grid, 6);
    printf("\n");

    printf("polynomial\n");
    printf(
        "1 - 2x + 3x^3 at x=2 = %.8f\n\n",
        num_polynomial(coefficients, 4, 2.0)
    );

    printf("numerical derivative\n");
    printf(
        "d/dx sin(x) at x=1 = %.8f\n",
        num_derivative(sine_function, 1.0, 1.0e-5)
    );
    printf("exact value         = %.8f\n\n", cos(1.0));

    printf("numerical integration\n");
    printf(
        "trapezoid integral of sin(x) from 0 to pi = %.10f\n",
        num_integrate_trapezoid(
            sine_function,
            0.0,
            PI,
            10000
        )
    );

    printf(
        "Simpson integral of sin(x) from 0 to pi   = %.10f\n\n",
        num_integrate_simpson(
            sine_function,
            0.0,
            PI,
            1000
        )
    );

    printf("root finding\n");

    success = num_bisection(
        root_function,
        0.0,
        2.0,
        1.0e-12,
        NUM_MAX_ITER,
        &root
    );

    printf(
        "bisection success = %d, root = %.12f\n",
        success,
        root
    );

    success = num_newton(
        root_function,
        root_derivative,
        1.0,
        1.0e-12,
        NUM_MAX_ITER,
        &root
    );

    printf(
        "Newton success    = %d, root = %.12f\n\n",
        success,
        root
    );

    printf("linear system\n");

    success = num_solve_linear(
        matrix,
        right_hand_side,
        3,
        solution
    );

    printf("solve success = %d\n", success);

    if (success) {
        printf("solution = ");
        num_print_vector(solution, 3);
    }

    return EXIT_SUCCESS;
}
