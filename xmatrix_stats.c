#include <ctype.h>
#include <errno.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>

typedef struct {
	float *data;
	size_t nrow;
	size_t ncol;
} matrix;

/* Read one arbitrarily long line from a file. */
static char *read_line(FILE *file) {
	char *line = NULL;
	size_t length = 0;
	size_t capacity = 0;
	int character;

	while ((character = fgetc(file)) != EOF) {
		if (length + 1 >= capacity) {
			size_t new_capacity =
					     capacity == 0 ? 128 : 2 * capacity;

			char *temporary = realloc(
				line,
				new_capacity * sizeof(*line)
				);

			if (temporary == NULL) {
				free(line);
				return NULL;
			}

			line = temporary;
			capacity = new_capacity;
		}

		if (character == '\n') {
			break;
		}

		line[length++] = (char)character;
	}

	if (character == EOF && length == 0) {
		free(line);
		return NULL;
	}

	line[length] = '\0';
	return line;
}

/* Parse all whitespace-separated floats from one line. */
static int parse_row(
		     const char *line,
		     float **values,
		     size_t *count
		    ) {
	float *row = NULL;
	size_t size = 0;
	size_t capacity = 0;
	const char *position = line;

	while (*position != '\0') {
		char *end;
		float value;

		while (isspace((unsigned char)*position)) {
			++position;
		}

		if (*position == '\0') {
			break;
		}

		errno = 0;
		value = strtof(position, &end);

		if (end == position || errno == ERANGE) {
			free(row);
			return 0;
		}

		if (size == capacity) {
			size_t new_capacity =
					     capacity == 0 ? 8 : 2 * capacity;

			float *temporary = realloc(
				row,
				new_capacity * sizeof(*row)
				);

			if (temporary == NULL) {
				free(row);
				return 0;
			}

			row = temporary;
			capacity = new_capacity;
		}

		row[size++] = value;
		position = end;
	}

	*values = row;
	*count = size;

	return 1;
}

/* Read a rectangular whitespace-separated matrix from a file. */
static int read_matrix(
		       const char *filename,
		       matrix *result
		      ) {
	FILE *file;
	float *data = NULL;
	size_t nrow = 0;
	size_t ncol = 0;
	size_t capacity_rows = 0;
	size_t line_number = 0;
	char *line;

	file = fopen(filename, "r");

	if (file == NULL) {
		perror(filename);
		return 0;
	}

	while ((line = read_line(file)) != NULL) {
		float *row = NULL;
		size_t row_size = 0;

		++line_number;

		if (!parse_row(line, &row, &row_size)) {
			fprintf(
				  stderr,
				  "Invalid value on line %zu.\n",
				  line_number
			       );

			free(line);
			free(data);
			fclose(file);
			return 0;
		}

		free(line);

		if (row_size == 0) {
			free(row);
			continue;
		}

		if (ncol == 0) {
			ncol = row_size;
		} else if (row_size != ncol) {
			fprintf(
				  stderr,
				  "Line %zu has %zu columns; expected %zu.\n",
				  line_number,
				  row_size,
				  ncol
			       );

			free(row);
			free(data);
			fclose(file);
			return 0;
		}

		if (nrow == capacity_rows) {
			size_t new_capacity_rows =
				capacity_rows == 0
				? 16
				  : 2 * capacity_rows;

			float *temporary = realloc(
				data,
				new_capacity_rows *
				ncol *
				sizeof(*data)
				);

			if (temporary == NULL) {
				fprintf(
					  stderr,
					  "Memory allocation failed.\n"
				       );

				free(row);
				free(data);
				fclose(file);
				return 0;
			}

			data = temporary;
			capacity_rows = new_capacity_rows;
		}

		{
			size_t column;

			for (column = 0; column < ncol; ++column) {
				data[nrow * ncol + column] = row[column];
			}
		}

		++nrow;
		free(row);
	}

	if (ferror(file)) {
		fprintf(stderr, "Error while reading %s.\n", filename);
		free(data);
		fclose(file);
		return 0;
	}

	fclose(file);

	if (nrow == 0 || ncol == 0) {
		fprintf(stderr, "The file contains no matrix data.\n");
		free(data);
		return 0;
	}

	result->data = data;
	result->nrow = nrow;
	result->ncol = ncol;

	return 1;
}

/* Release storage owned by a matrix. */
static void free_matrix(matrix *x) {
	free(x->data);

	x->data = NULL;
	x->nrow = 0;
	x->ncol = 0;
}

/* Compute and print summary statistics for each column. */
static void print_column_statistics(
				    const matrix *x,
				    double means[]
				   ) {
	size_t column;

	printf(
	       "%-8s %14s %14s %14s %14s %14s\n",
	       "column",
	       "first",
	       "last",
	       "min",
	       "max",
	       "mean"
	      );

	for (column = 0; column < x->ncol; ++column) {
		float minimum = x->data[column];
		float maximum = x->data[column];
		double sum = 0.0;
		size_t row;

		for (row = 0; row < x->nrow; ++row) {
			float value =
				     x->data[row * x->ncol + column];

			if (value < minimum) {
				minimum = value;
			}

			if (value > maximum) {
				maximum = value;
			}

			sum += value;
		}

		means[column] = sum / x->nrow;

		printf(
		       "%-8zu %14.6g %14.6g %14.6g %14.6g %14.6g\n",
		       column + 1,
		       x->data[column],
		       x->data[
			       (x->nrow - 1) * x->ncol + column
			      ],
		       minimum,
		       maximum,
		       means[column]
		      );
	}
}

/* Compute the Pearson correlation matrix of the columns. */
static void compute_correlation_matrix(
				       const matrix *x,
				       const double means[],
				       double correlation[]
				      ) {
	double *sumsq;
	size_t first;
	size_t second;

	sumsq = calloc(x->ncol, sizeof(*sumsq));

	if (sumsq == NULL) {
		fprintf(stderr, "Memory allocation failed.\n");
		exit(EXIT_FAILURE);
	}

	for (first = 0; first < x->ncol; ++first) {
		size_t row;

		for (row = 0; row < x->nrow; ++row) {
			double difference =
					   x->data[row * x->ncol + first] -
					   means[first];

			sumsq[first] += difference * difference;
		}
	}

	for (first = 0; first < x->ncol; ++first) {
		for (second = 0; second < x->ncol; ++second) {
			double cross_product = 0.0;
			double denominator;
			size_t row;

			for (row = 0; row < x->nrow; ++row) {
				double difference_first =
					x->data[row * x->ncol + first] -
					means[first];

				double difference_second =
					x->data[row * x->ncol + second] -
					means[second];

				cross_product +=
						difference_first *
						difference_second;
			}

			denominator =
				     sqrt(sumsq[first] * sumsq[second]);

			if (denominator == 0.0) {
				correlation[
					    first * x->ncol + second
					   ] = NAN;
			} else {
				correlation[
					    first * x->ncol + second
					   ] =
					      cross_product / denominator;
			}
		}
	}

	free(sumsq);
}

/* Print a square correlation matrix. */
static void print_correlation_matrix(
				     const double correlation[],
				     size_t ncol
				    ) {
	size_t row;
	size_t column;

	printf("\ncorrelation matrix\n");
	printf("%8s", "");

	for (column = 0; column < ncol; ++column) {
		printf("%12zu", column + 1);
	}

	printf("\n");

	for (row = 0; row < ncol; ++row) {
		printf("%8zu", row + 1);

		for (column = 0; column < ncol; ++column) {
			printf(
			       "%12.6f",
			       correlation[row * ncol + column]
			      );
		}

		printf("\n");
	}
}

/* Read a matrix and print column statistics and correlations. */
int main(int argc, char *argv[]) {
	matrix x = {NULL, 0, 0};
	double *means;
	double *correlation;

	if (argc != 2) {
		fprintf(
			  stderr,
			  "Usage: %s matrix.txt\n",
			  argv[0]
		       );

		return EXIT_FAILURE;
	}

	if (!read_matrix(argv[1], &x)) {
		return EXIT_FAILURE;
	}

	means = malloc(
		       x.ncol * sizeof(*means)
		      );

	correlation = malloc(
			     x.ncol * x.ncol * sizeof(*correlation)
			    );

	if (means == NULL || correlation == NULL) {
		fprintf(stderr, "Memory allocation failed.\n");

		free(means);
		free(correlation);
		free_matrix(&x);

		return EXIT_FAILURE;
	}

	printf("rows = %zu\n", x.nrow);
	printf("columns = %zu\n\n", x.ncol);

	print_column_statistics(&x, means);

	compute_correlation_matrix(
				   &x,
				   means,
				   correlation
				  );

	print_correlation_matrix(
				 correlation,
				 x.ncol
				);

	free(means);
	free(correlation);
	free_matrix(&x);

	return EXIT_SUCCESS;
}
