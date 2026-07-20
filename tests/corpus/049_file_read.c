#include <stdio.h>

int main(void) {
    FILE *file = fopen("numbers.txt", "r");
    int x;
    int y;

    if (file == NULL) {
        return 1;
    }

    while (fscanf(file, "%d %d", &x, &y) == 2) {
        printf("%d %d\n", x, y);
    }

    fclose(file);
    return 0;
}
