#include <stdio.h>

int main(void) {
    char text[] = "transpiler";
    int i = 0;

    while (text[i] != '\0') {
        printf("%c\n", text[i]);
        ++i;
    }

    return 0;
}
