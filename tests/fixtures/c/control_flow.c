#include <stdio.h>

int main(void) {
    int i;
    int code = 2;

    if (code > 0) {
        printf("positive\n");
    } else {
        printf("nonpositive\n");
    }
    for (i = 0; i < 3; ++i) {
        printf("%d\n", i);
    }
    switch (code) {
        case 1:
            printf("one\n");
            break;
        case 2:
            printf("two\n");
            break;
        default:
            printf("other\n");
            break;
    }
    return 0;
}
