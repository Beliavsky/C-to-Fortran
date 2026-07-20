#include <stdio.h>
#include <stdlib.h>

struct vector {
    int length;
    double data[];
};

int main(void) {
    int n = 5;
    struct vector *v = malloc(
        sizeof(*v) + (size_t)n * sizeof(v->data[0])
    );
    int i;

    if (v == NULL) {
        return 1;
    }

    v->length = n;

    for (i = 0; i < n; ++i) {
        v->data[i] = i * 1.5;
    }

    for (i = 0; i < v->length; ++i) {
        printf("%.2f\n", v->data[i]);
    }

    free(v);
    return 0;
}
