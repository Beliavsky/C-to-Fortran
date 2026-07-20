#include <stdio.h>

int binary_search(const int x[], int n, int target) {
    int left = 0;
    int right = n - 1;

    while (left <= right) {
        int middle = left + (right - left) / 2;

        if (x[middle] == target) {
            return middle;
        } else if (x[middle] < target) {
            left = middle + 1;
        } else {
            right = middle - 1;
        }
    }

    return -1;
}

int main(void) {
    int x[] = {1, 3, 5, 7, 9, 11, 13};

    printf("%d\n", binary_search(x, 7, 9));
    printf("%d\n", binary_search(x, 7, 8));

    return 0;
}
