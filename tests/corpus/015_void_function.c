#include <stdio.h>

void print_line(char ch, int n) {
    int i;

    for (i = 0; i < n; ++i) {
        putchar(ch);
    }
    putchar('\n');
}

int main(void) {
    print_line('*', 12);
    return 0;
}
