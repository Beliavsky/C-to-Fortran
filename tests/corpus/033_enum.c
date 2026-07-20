#include <stdio.h>

enum color {
    RED,
    GREEN,
    BLUE
};

int main(void) {
    enum color c = GREEN;

    if (c == GREEN) {
        printf("green\n");
    }

    return 0;
}
