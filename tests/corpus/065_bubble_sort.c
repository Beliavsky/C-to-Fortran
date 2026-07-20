#include <stdio.h>

void bubble_sort(int x[], int n) {
    int i;
    int j;

    for (i = 0; i < n - 1; ++i) {
        for (j = 0; j < n - i - 1; ++j) {
            if (x[j] > x[j + 1]) {
                int temporary = x[j];
                x[j] = x[j + 1];
                x[j + 1] = temporary;
            }
        }
    }
}

int main(void) {
    int x[] = {5, 1, 4, 2, 8, 0};
    int i;

    bubble_sort(x, 6);

    for (i = 0; i < 6; ++i) {
        printf("%d\n", x[i]);
    }

    return 0;
}
