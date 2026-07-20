#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define NOBS 20000
#define NCOMP 3
#define NDIM 2

#define MAX_ITER 1000
#define TOL 1.0e-8
#define MIN_WEIGHT 1.0e-10
#define COV_REG 1.0e-6
#define PI 3.14159265358979323846

typedef struct {
    int ncomp;
    int ndim;
    double *weight;
    double *mean;
    double *covariance;
    int iterations;
    double loglik;
    int converged;
} mixture_fit;

/* Return element (row, column) of a row-major matrix. */
static size_t matrix_index(
    int row,
    int column,
    int ncolumn
) {
    return (size_t)row * ncolumn + column;
}

/* Return the index of a component mean element. */
static size_t mean_index(
    int component,
    int dimension,
    int ndim
) {
    return (size_t)component * ndim + dimension;
}

/* Return the index of a component covariance element. */
static size_t covariance_index(
    int component,
    int row,
    int column,
    int ndim
) {
    return (
        ((size_t)component * ndim + row) * ndim +
        column
    );
}

/* Return a uniform random variate on (0, 1). */
static double uniform_random(void) {
    return ((double)rand() + 1.0) /
           ((double)RAND_MAX + 2.0);
}

/* Return a standard normal variate using Box-Muller. */
static double normal_random(void) {
    static int has_spare = 0;
    static double spare;
    double u1;
    double u2;
    double radius;
    double angle;

    if (has_spare) {
        has_spare = 0;
        return spare;
    }

    u1 = uniform_random();
    u2 = uniform_random();

    radius = sqrt(-2.0 * log(u1));
    angle = 2.0 * PI * u2;

    spare = radius * sin(angle);
    has_spare = 1;

    return radius * cos(angle);
}

/* Normalize positive mixture weights to sum to one. */
static void normalize_weights(
    double weight[],
    int ncomp
) {
    double sum = 0.0;
    int component;

    for (component = 0; component < ncomp; ++component) {
        if (weight[component] < MIN_WEIGHT) {
            weight[component] = MIN_WEIGHT;
        }

        sum += weight[component];
    }

    for (component = 0; component < ncomp; ++component) {
        weight[component] /= sum;
    }
}

/* Draw a component index from categorical probabilities. */
static int categorical_random(
    const double weight[],
    int ncomp
) {
    double u = uniform_random();
    double cumulative = 0.0;
    int component;

    for (component = 0; component < ncomp; ++component) {
        cumulative += weight[component];

        if (u < cumulative) {
            return component;
        }
    }

    return ncomp - 1;
}

/* Set a square matrix to zero. */
static void zero_matrix(
    double matrix[],
    int ndim
) {
    size_t count = (size_t)ndim * ndim;
    size_t i;

    for (i = 0; i < count; ++i) {
        matrix[i] = 0.0;
    }
}

/* Set a square matrix to the identity matrix. */
static void identity_matrix(
    double matrix[],
    int ndim
) {
    int row;
    int column;

    zero_matrix(matrix, ndim);

    for (row = 0; row < ndim; ++row) {
        column = row;
        matrix[matrix_index(row, column, ndim)] = 1.0;
    }
}

/* Compute the lower Cholesky factor of a positive-definite matrix. */
static int cholesky_decompose(
    const double matrix[],
    double lower[],
    int ndim
) {
    int row;
    int column;
    int k;

    zero_matrix(lower, ndim);

    for (row = 0; row < ndim; ++row) {
        for (column = 0; column <= row; ++column) {
            double sum =
                matrix[matrix_index(row, column, ndim)];

            for (k = 0; k < column; ++k) {
                sum -=
                    lower[matrix_index(row, k, ndim)] *
                    lower[matrix_index(column, k, ndim)];
            }

            if (row == column) {
                if (sum <= 0.0 || !isfinite(sum)) {
                    return 0;
                }

                lower[matrix_index(row, column, ndim)] =
                    sqrt(sum);
            } else {
                lower[matrix_index(row, column, ndim)] =
                    sum /
                    lower[matrix_index(column, column, ndim)];
            }
        }
    }

    return 1;
}

/* Solve a lower-triangular linear system. */
static void solve_lower_triangular(
    const double lower[],
    const double b[],
    double x[],
    int ndim
) {
    int row;
    int column;

    for (row = 0; row < ndim; ++row) {
        double sum = b[row];

        for (column = 0; column < row; ++column) {
            sum -=
                lower[matrix_index(row, column, ndim)] *
                x[column];
        }

        x[row] =
            sum /
            lower[matrix_index(row, row, ndim)];
    }
}

/* Compute log(sum(exp(x))) stably. */
static double log_sum_exp(
    const double x[],
    int n
) {
    double maximum = x[0];
    double sum = 0.0;
    int i;

    for (i = 1; i < n; ++i) {
        if (x[i] > maximum) {
            maximum = x[i];
        }
    }

    for (i = 0; i < n; ++i) {
        sum += exp(x[i] - maximum);
    }

    return maximum + log(sum);
}

/* Evaluate a multivariate normal log density. */
static double multivariate_normal_log_density(
    const double x[],
    const double mean[],
    const double covariance[],
    int ndim,
    double lower[],
    double difference[],
    double solution[]
) {
    double quadratic = 0.0;
    double log_determinant = 0.0;
    int dimension;

    if (!cholesky_decompose(covariance, lower, ndim)) {
        return -INFINITY;
    }

    for (dimension = 0; dimension < ndim; ++dimension) {
        difference[dimension] =
            x[dimension] - mean[dimension];

        log_determinant +=
            2.0 *
            log(lower[matrix_index(
                dimension,
                dimension,
                ndim
            )]);
    }

    solve_lower_triangular(
        lower,
        difference,
        solution,
        ndim
    );

    for (dimension = 0; dimension < ndim; ++dimension) {
        quadratic += solution[dimension] * solution[dimension];
    }

    return -0.5 * (
        ndim * log(2.0 * PI) +
        log_determinant +
        quadratic
    );
}

/* Generate true mixture parameters algorithmically. */
static void generate_true_parameters(
    int ncomp,
    int ndim,
    double weight[],
    double mean[],
    double covariance[]
) {
    int component;
    int row;
    int column;

    for (component = 0; component < ncomp; ++component) {
        double centered_component =
            component - 0.5 * (ncomp - 1);

        weight[component] = component + 1.0;

        for (row = 0; row < ndim; ++row) {
            double sign = row % 2 == 0 ? 1.0 : -1.0;

            mean[mean_index(component, row, ndim)] =
                sign * 4.0 * centered_component +
                0.75 * row;
        }

        for (row = 0; row < ndim; ++row) {
            for (column = 0; column < ndim; ++column) {
                double value;

                if (row == column) {
                    double sd =
                        0.7 +
                        0.15 * ((component + row) % 4);

                    value = sd * sd;
                } else {
                    double sd_row =
                        0.7 +
                        0.15 * ((component + row) % 4);

                    double sd_column =
                        0.7 +
                        0.15 * ((component + column) % 4);

                    double correlation =
                        0.20 /
                        (1.0 + abs(row - column));

                    if ((component + row + column) % 2 != 0) {
                        correlation = -correlation;
                    }

                    value =
                        correlation *
                        sd_row *
                        sd_column;
                }

                covariance[covariance_index(
                    component,
                    row,
                    column,
                    ndim
                )] = value;
            }
        }
    }

    normalize_weights(weight, ncomp);
}

/* Simulate one multivariate normal observation. */
static void simulate_multivariate_normal(
    double x[],
    const double mean[],
    const double covariance[],
    int ndim,
    double lower[],
    double z[]
) {
    int row;
    int column;

    if (!cholesky_decompose(covariance, lower, ndim)) {
        fprintf(stderr, "True covariance is not positive definite.\n");
        exit(EXIT_FAILURE);
    }

    for (row = 0; row < ndim; ++row) {
        z[row] = normal_random();
    }

    for (row = 0; row < ndim; ++row) {
        double value = mean[row];

        for (column = 0; column <= row; ++column) {
            value +=
                lower[matrix_index(row, column, ndim)] *
                z[column];
        }

        x[row] = value;
    }
}

/* Simulate data from a multivariate normal mixture. */
static void simulate_mixture(
    double data[],
    int nobs,
    int ncomp,
    int ndim,
    const double weight[],
    const double mean[],
    const double covariance[]
) {
    double *lower;
    double *z;
    int observation;

    lower = malloc(
        (size_t)ndim * ndim * sizeof(*lower)
    );

    z = malloc(
        (size_t)ndim * sizeof(*z)
    );

    if (lower == NULL || z == NULL) {
        free(lower);
        free(z);

        fprintf(stderr, "Memory allocation failed.\n");
        exit(EXIT_FAILURE);
    }

    for (observation = 0; observation < nobs; ++observation) {
        int component =
            categorical_random(weight, ncomp);

        simulate_multivariate_normal(
            &data[(size_t)observation * ndim],
            &mean[(size_t)component * ndim],
            &covariance[(size_t)component * ndim * ndim],
            ndim,
            lower,
            z
        );
    }

    free(lower);
    free(z);
}

/* Allocate arrays for a fitted mixture model. */
static mixture_fit allocate_mixture_fit(
    int ncomp,
    int ndim
) {
    mixture_fit fit;

    fit.ncomp = ncomp;
    fit.ndim = ndim;

    fit.weight = malloc(
        (size_t)ncomp * sizeof(*fit.weight)
    );

    fit.mean = malloc(
        (size_t)ncomp * ndim * sizeof(*fit.mean)
    );

    fit.covariance = malloc(
        (size_t)ncomp * ndim * ndim *
        sizeof(*fit.covariance)
    );

    fit.iterations = 0;
    fit.loglik = -INFINITY;
    fit.converged = 0;

    if (
        fit.weight == NULL ||
        fit.mean == NULL ||
        fit.covariance == NULL
    ) {
        free(fit.weight);
        free(fit.mean);
        free(fit.covariance);

        fprintf(stderr, "Memory allocation failed.\n");
        exit(EXIT_FAILURE);
    }

    return fit;
}

/* Release arrays owned by a fitted mixture model. */
static void free_mixture_fit(
    mixture_fit *fit
) {
    free(fit->weight);
    free(fit->mean);
    free(fit->covariance);

    fit->weight = NULL;
    fit->mean = NULL;
    fit->covariance = NULL;
    fit->ncomp = 0;
    fit->ndim = 0;
}

/* Compute the sample mean vector. */
static void sample_mean_vector(
    const double data[],
    int nobs,
    int ndim,
    double mean[]
) {
    int observation;
    int dimension;

    for (dimension = 0; dimension < ndim; ++dimension) {
        mean[dimension] = 0.0;
    }

    for (observation = 0; observation < nobs; ++observation) {
        for (dimension = 0; dimension < ndim; ++dimension) {
            mean[dimension] +=
                data[(size_t)observation * ndim + dimension];
        }
    }

    for (dimension = 0; dimension < ndim; ++dimension) {
        mean[dimension] /= nobs;
    }
}

/* Compute the sample covariance matrix. */
static void sample_covariance_matrix(
    const double data[],
    int nobs,
    int ndim,
    const double mean[],
    double covariance[]
) {
    int observation;
    int row;
    int column;

    zero_matrix(covariance, ndim);

    for (observation = 0; observation < nobs; ++observation) {
        for (row = 0; row < ndim; ++row) {
            double difference_row =
                data[(size_t)observation * ndim + row] -
                mean[row];

            for (column = 0; column < ndim; ++column) {
                double difference_column =
                    data[
                        (size_t)observation * ndim +
                        column
                    ] -
                    mean[column];

                covariance[
                    matrix_index(row, column, ndim)
                ] +=
                    difference_row *
                    difference_column;
            }
        }
    }

    for (row = 0; row < ndim; ++row) {
        for (column = 0; column < ndim; ++column) {
            covariance[
                matrix_index(row, column, ndim)
            ] /= nobs - 1;
        }

        covariance[matrix_index(row, row, ndim)] +=
            COV_REG;
    }
}

/* Initialize parameters from evenly spaced observations. */
static void initialize_mixture(
    mixture_fit *fit,
    const double data[],
    int nobs
) {
    double *overall_mean;
    double *overall_covariance;
    int component;
    int dimension;
    int row;
    int column;

    overall_mean = malloc(
        (size_t)fit->ndim * sizeof(*overall_mean)
    );

    overall_covariance = malloc(
        (size_t)fit->ndim * fit->ndim *
        sizeof(*overall_covariance)
    );

    if (
        overall_mean == NULL ||
        overall_covariance == NULL
    ) {
        free(overall_mean);
        free(overall_covariance);

        fprintf(stderr, "Memory allocation failed.\n");
        exit(EXIT_FAILURE);
    }

    sample_mean_vector(
        data,
        nobs,
        fit->ndim,
        overall_mean
    );

    sample_covariance_matrix(
        data,
        nobs,
        fit->ndim,
        overall_mean,
        overall_covariance
    );

    for (component = 0; component < fit->ncomp; ++component) {
        int observation =
            (int)(
                ((double)component + 0.5) /
                fit->ncomp *
                nobs
            );

        if (observation >= nobs) {
            observation = nobs - 1;
        }

        fit->weight[component] =
            1.0 / fit->ncomp;

        for (dimension = 0;
             dimension < fit->ndim;
             ++dimension) {
            fit->mean[
                mean_index(
                    component,
                    dimension,
                    fit->ndim
                )
            ] =
                data[
                    (size_t)observation * fit->ndim +
                    dimension
                ];
        }

        for (row = 0; row < fit->ndim; ++row) {
            for (column = 0;
                 column < fit->ndim;
                 ++column) {
                fit->covariance[
                    covariance_index(
                        component,
                        row,
                        column,
                        fit->ndim
                    )
                ] =
                    overall_covariance[
                        matrix_index(
                            row,
                            column,
                            fit->ndim
                        )
                    ];
            }
        }
    }

    free(overall_mean);
    free(overall_covariance);
}

/* Compute the multivariate mixture log-likelihood. */
static double mixture_loglik(
    const double data[],
    int nobs,
    const mixture_fit *fit
) {
    double *log_terms;
    double *lower;
    double *difference;
    double *solution;
    double loglik = 0.0;
    int observation;
    int component;

    log_terms = malloc(
        (size_t)fit->ncomp * sizeof(*log_terms)
    );

    lower = malloc(
        (size_t)fit->ndim * fit->ndim *
        sizeof(*lower)
    );

    difference = malloc(
        (size_t)fit->ndim * sizeof(*difference)
    );

    solution = malloc(
        (size_t)fit->ndim * sizeof(*solution)
    );

    if (
        log_terms == NULL ||
        lower == NULL ||
        difference == NULL ||
        solution == NULL
    ) {
        free(log_terms);
        free(lower);
        free(difference);
        free(solution);

        fprintf(stderr, "Memory allocation failed.\n");
        exit(EXIT_FAILURE);
    }

    for (observation = 0; observation < nobs; ++observation) {
        const double *x =
            &data[(size_t)observation * fit->ndim];

        for (component = 0;
             component < fit->ncomp;
             ++component) {
            log_terms[component] =
                log(fit->weight[component]) +
                multivariate_normal_log_density(
                    x,
                    &fit->mean[
                        (size_t)component * fit->ndim
                    ],
                    &fit->covariance[
                        (size_t)component *
                        fit->ndim *
                        fit->ndim
                    ],
                    fit->ndim,
                    lower,
                    difference,
                    solution
                );
        }

        loglik += log_sum_exp(
            log_terms,
            fit->ncomp
        );
    }

    free(log_terms);
    free(lower);
    free(difference);
    free(solution);

    return loglik;
}

/* Fit a multivariate normal mixture using EM. */
static mixture_fit fit_normal_mixture(
    const double data[],
    int nobs,
    int ncomp,
    int ndim
) {
    mixture_fit fit;
    double *effective_count;
    double *new_mean;
    double *new_covariance;
    double *log_terms;
    double *responsibility;
    double *lower;
    double *difference;
    double *solution;
    double previous_loglik = -INFINITY;
    int iteration;
    int observation;
    int component;
    int row;
    int column;

    if (
        nobs < 2 ||
        ncomp < 1 ||
        ndim < 1 ||
        ncomp > nobs
    ) {
        fprintf(
            stderr,
            "Require nobs >= 2, ncomp >= 1, ndim >= 1, "
            "and ncomp <= nobs.\n"
        );
        exit(EXIT_FAILURE);
    }

    fit = allocate_mixture_fit(ncomp, ndim);
    initialize_mixture(&fit, data, nobs);

    effective_count = malloc(
        (size_t)ncomp * sizeof(*effective_count)
    );

    new_mean = malloc(
        (size_t)ncomp * ndim * sizeof(*new_mean)
    );

    new_covariance = malloc(
        (size_t)ncomp * ndim * ndim *
        sizeof(*new_covariance)
    );

    log_terms = malloc(
        (size_t)ncomp * sizeof(*log_terms)
    );

    responsibility = malloc(
        (size_t)nobs * ncomp *
        sizeof(*responsibility)
    );

    lower = malloc(
        (size_t)ndim * ndim * sizeof(*lower)
    );

    difference = malloc(
        (size_t)ndim * sizeof(*difference)
    );

    solution = malloc(
        (size_t)ndim * sizeof(*solution)
    );

    if (
        effective_count == NULL ||
        new_mean == NULL ||
        new_covariance == NULL ||
        log_terms == NULL ||
        responsibility == NULL ||
        lower == NULL ||
        difference == NULL ||
        solution == NULL
    ) {
        free(effective_count);
        free(new_mean);
        free(new_covariance);
        free(log_terms);
        free(responsibility);
        free(lower);
        free(difference);
        free(solution);
        free_mixture_fit(&fit);

        fprintf(stderr, "Memory allocation failed.\n");
        exit(EXIT_FAILURE);
    }

    for (iteration = 1; iteration <= MAX_ITER; ++iteration) {
        memset(
            effective_count,
            0,
            (size_t)ncomp * sizeof(*effective_count)
        );

        memset(
            new_mean,
            0,
            (size_t)ncomp * ndim * sizeof(*new_mean)
        );

        memset(
            new_covariance,
            0,
            (size_t)ncomp * ndim * ndim *
            sizeof(*new_covariance)
        );

        for (observation = 0;
             observation < nobs;
             ++observation) {
            const double *x =
                &data[(size_t)observation * ndim];

            double denominator;

            for (component = 0;
                 component < ncomp;
                 ++component) {
                log_terms[component] =
                    log(fit.weight[component]) +
                    multivariate_normal_log_density(
                        x,
                        &fit.mean[
                            (size_t)component * ndim
                        ],
                        &fit.covariance[
                            (size_t)component *
                            ndim *
                            ndim
                        ],
                        ndim,
                        lower,
                        difference,
                        solution
                    );
            }

            denominator =
                log_sum_exp(log_terms, ncomp);

            for (component = 0;
                 component < ncomp;
                 ++component) {
                double value =
                    exp(
                        log_terms[component] -
                        denominator
                    );

                responsibility[
                    (size_t)observation * ncomp +
                    component
                ] = value;

                effective_count[component] += value;

                for (row = 0; row < ndim; ++row) {
                    new_mean[
                        mean_index(
                            component,
                            row,
                            ndim
                        )
                    ] += value * x[row];
                }
            }
        }

        for (component = 0;
             component < ncomp;
             ++component) {
            if (
                effective_count[component] <
                MIN_WEIGHT * nobs
            ) {
                effective_count[component] =
                    MIN_WEIGHT * nobs;
            }

            fit.weight[component] =
                effective_count[component] /
                nobs;

            for (row = 0; row < ndim; ++row) {
                fit.mean[
                    mean_index(
                        component,
                        row,
                        ndim
                    )
                ] =
                    new_mean[
                        mean_index(
                            component,
                            row,
                            ndim
                        )
                    ] /
                    effective_count[component];
            }
        }

        normalize_weights(fit.weight, ncomp);

        for (observation = 0;
             observation < nobs;
             ++observation) {
            const double *x =
                &data[(size_t)observation * ndim];

            for (component = 0;
                 component < ncomp;
                 ++component) {
                double value =
                    responsibility[
                        (size_t)observation * ncomp +
                        component
                    ];

                for (row = 0; row < ndim; ++row) {
                    double difference_row =
                        x[row] -
                        fit.mean[
                            mean_index(
                                component,
                                row,
                                ndim
                            )
                        ];

                    for (column = 0;
                         column < ndim;
                         ++column) {
                        double difference_column =
                            x[column] -
                            fit.mean[
                                mean_index(
                                    component,
                                    column,
                                    ndim
                                )
                            ];

                        new_covariance[
                            covariance_index(
                                component,
                                row,
                                column,
                                ndim
                            )
                        ] +=
                            value *
                            difference_row *
                            difference_column;
                    }
                }
            }
        }

        for (component = 0;
             component < ncomp;
             ++component) {
            for (row = 0; row < ndim; ++row) {
                for (column = 0;
                     column < ndim;
                     ++column) {
                    double value =
                        new_covariance[
                            covariance_index(
                                component,
                                row,
                                column,
                                ndim
                            )
                        ] /
                        effective_count[component];

                    if (row == column) {
                        value += COV_REG;
                    }

                    fit.covariance[
                        covariance_index(
                            component,
                            row,
                            column,
                            ndim
                        )
                    ] = value;
                }
            }
        }

        fit.loglik = mixture_loglik(
            data,
            nobs,
            &fit
        );

        fit.iterations = iteration;

        if (
            iteration > 1 &&
            fabs(fit.loglik - previous_loglik) <
                TOL * (1.0 + fabs(previous_loglik))
        ) {
            fit.converged = 1;
            break;
        }

        previous_loglik = fit.loglik;
    }

    free(effective_count);
    free(new_mean);
    free(new_covariance);
    free(log_terms);
    free(responsibility);
    free(lower);
    free(difference);
    free(solution);

    return fit;
}

/* Exchange two double values. */
static void swap_double(
    double *a,
    double *b
) {
    double temporary = *a;
    *a = *b;
    *b = temporary;
}

/* Exchange two mixture components. */
static void swap_components(
    mixture_fit *fit,
    int first,
    int second
) {
    int row;
    int column;

    swap_double(
        &fit->weight[first],
        &fit->weight[second]
    );

    for (row = 0; row < fit->ndim; ++row) {
        swap_double(
            &fit->mean[
                mean_index(first, row, fit->ndim)
            ],
            &fit->mean[
                mean_index(second, row, fit->ndim)
            ]
        );
    }

    for (row = 0; row < fit->ndim; ++row) {
        for (column = 0;
             column < fit->ndim;
             ++column) {
            swap_double(
                &fit->covariance[
                    covariance_index(
                        first,
                        row,
                        column,
                        fit->ndim
                    )
                ],
                &fit->covariance[
                    covariance_index(
                        second,
                        row,
                        column,
                        fit->ndim
                    )
                ]
            );
        }
    }
}

/* Sort fitted components by the first mean coordinate. */
static void sort_components(
    mixture_fit *fit
) {
    int first;
    int second;

    for (first = 0;
         first < fit->ncomp - 1;
         ++first) {
        for (second = first + 1;
             second < fit->ncomp;
             ++second) {
            if (
                fit->mean[
                    mean_index(first, 0, fit->ndim)
                ] >
                fit->mean[
                    mean_index(second, 0, fit->ndim)
                ]
            ) {
                swap_components(
                    fit,
                    first,
                    second
                );
            }
        }
    }
}

/* Print a vector on one line. */
static void print_vector(
    const double vector[],
    int n
) {
    int i;

    printf("[");

    for (i = 0; i < n; ++i) {
        printf("%10.5f", vector[i]);

        if (i < n - 1) {
            printf(" ");
        }
    }

    printf("]");
}

/* Print a square matrix. */
static void print_matrix(
    const double matrix[],
    int ndim
) {
    int row;
    int column;

    for (row = 0; row < ndim; ++row) {
        printf("    [");

        for (column = 0; column < ndim; ++column) {
            printf(
                "%10.5f",
                matrix[
                    matrix_index(row, column, ndim)
                ]
            );

            if (column < ndim - 1) {
                printf(" ");
            }
        }

        printf("]\n");
    }
}

/* Print true and fitted mixture parameters. */
static void print_results(
    const mixture_fit *fit,
    const double true_weight[],
    const double true_mean[],
    const double true_covariance[]
) {
    int component;

    printf("nobs = %d\n", NOBS);
    printf("ncomp = %d\n", fit->ncomp);
    printf("ndim = %d\n", fit->ndim);
    printf("iterations = %d\n", fit->iterations);
    printf(
        "converged = %s\n",
        fit->converged ? "yes" : "no"
    );
    printf("log-likelihood = %.6f\n", fit->loglik);

    for (component = 0;
         component < fit->ncomp;
         ++component) {
        printf("\ncomponent %d\n", component + 1);

        printf(
            "weight: true = %.6f, fitted = %.6f\n",
            true_weight[component],
            fit->weight[component]
        );

        printf("true mean:   ");
        print_vector(
            &true_mean[(size_t)component * fit->ndim],
            fit->ndim
        );
        printf("\n");

        printf("fitted mean: ");
        print_vector(
            &fit->mean[(size_t)component * fit->ndim],
            fit->ndim
        );
        printf("\n");

        printf("true covariance:\n");
        print_matrix(
            &true_covariance[
                (size_t)component *
                fit->ndim *
                fit->ndim
            ],
            fit->ndim
        );

        printf("fitted covariance:\n");
        print_matrix(
            &fit->covariance[
                (size_t)component *
                fit->ndim *
                fit->ndim
            ],
            fit->ndim
        );
    }
}

/* Simulate data, fit the mixture, and print results. */
int main(void) {
    double *true_weight;
    double *true_mean;
    double *true_covariance;
    double *data;
    mixture_fit fit;

    if (
        NOBS < 2 ||
        NCOMP < 1 ||
        NDIM < 1 ||
        NCOMP > NOBS
    ) {
        fprintf(stderr, "Invalid NOBS, NCOMP, or NDIM.\n");
        return EXIT_FAILURE;
    }

    true_weight = malloc(
        (size_t)NCOMP * sizeof(*true_weight)
    );

    true_mean = malloc(
        (size_t)NCOMP * NDIM *
        sizeof(*true_mean)
    );

    true_covariance = malloc(
        (size_t)NCOMP * NDIM * NDIM *
        sizeof(*true_covariance)
    );

    data = malloc(
        (size_t)NOBS * NDIM *
        sizeof(*data)
    );

    if (
        true_weight == NULL ||
        true_mean == NULL ||
        true_covariance == NULL ||
        data == NULL
    ) {
        free(true_weight);
        free(true_mean);
        free(true_covariance);
        free(data);

        fprintf(stderr, "Memory allocation failed.\n");
        return EXIT_FAILURE;
    }

    srand(12345U);

    generate_true_parameters(
        NCOMP,
        NDIM,
        true_weight,
        true_mean,
        true_covariance
    );

    simulate_mixture(
        data,
        NOBS,
        NCOMP,
        NDIM,
        true_weight,
        true_mean,
        true_covariance
    );

    fit = fit_normal_mixture(
        data,
        NOBS,
        NCOMP,
        NDIM
    );

    sort_components(&fit);

    print_results(
        &fit,
        true_weight,
        true_mean,
        true_covariance
    );

    free_mixture_fit(&fit);
    free(true_weight);
    free(true_mean);
    free(true_covariance);
    free(data);

    return EXIT_SUCCESS;
}
