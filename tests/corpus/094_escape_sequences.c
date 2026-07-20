#include <stdio.h>

int main(void) {
    printf("tab:\tvalue\n");
    printf("quote: \"text\"\n");
    printf("backslash: \\\n");
    printf("characters: %c %c\n", '\x41', '\101');

    return 0;
}
