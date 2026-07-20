#include <stdio.h>

int global_count = 3;

void add_to_count(int x) {
    global_count += x;
}

int main(void) {
    add_to_count(7);
    printf("%d\n", global_count);
    return 0;
}
