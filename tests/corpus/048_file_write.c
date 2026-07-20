#include <stdio.h>

int main(void) {
    FILE *file = fopen("numbers.txt", "w");
    int i;

    if (file == NULL) {
        return 1;
    }

    for (i = 1; i <= 5; ++i) {
        fprintf(file, "%d %d\n", i, i * i);
    }

    fclose(file);
    return 0;
}
