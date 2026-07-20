#include <stdio.h>

int main(void) {
    int x = -3;

    if (x > 0) {
        printf("positive\n");
    } else if (x < 0) {
        printf("negative\n");
    } else {
        printf("zero\n");
    }

    return 0;
}
