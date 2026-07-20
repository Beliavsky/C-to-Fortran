#include <stdio.h>

int linear_search(const int x[], int n, int target) {
    int i;

    for (i = 0; i < n; ++i) {
        if (x[i] == target) {
            return i;
        }
    }

    return -1;
}

int main(void) {
    int x[] = {3, 8, 2, 9, 5};

    printf("%d\n", linear_search(x, 5, 9));
    printf("%d\n", linear_search(x, 5, 7));

    return 0;
}
