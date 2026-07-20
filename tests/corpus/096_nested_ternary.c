#include <stdio.h>

const char *classify(int x) {
    return x < 0 ? "negative" :
           x == 0 ? "zero" :
                    "positive";
}

int main(void) {
    printf("%s\n", classify(-1));
    printf("%s\n", classify(0));
    printf("%s\n", classify(1));

    return 0;
}
