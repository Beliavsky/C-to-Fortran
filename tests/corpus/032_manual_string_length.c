#include <stdio.h>

int string_length(const char s[]) {
    int n = 0;

    while (s[n] != '\0') {
        ++n;
    }

    return n;
}

int main(void) {
    printf("%d\n", string_length("abcdef"));
    return 0;
}
