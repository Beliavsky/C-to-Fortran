#include <stdio.h>

int array_sum(const int x[], int n) {
    int i;
    int sum = 0;
    for (i = 0; i < n; ++i) {
        sum += x[i];
    }
    return sum;
}

int main(void) {
    int values[] = {1, 2, 3, 4};
    printf("%d\n", array_sum(values, 4));
    return 0;
}
