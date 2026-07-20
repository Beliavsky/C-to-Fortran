#include <stdio.h>
#include <string.h>

int main(void) {
    char a[64] = "C to ";
    const char *b = "Fortran";

    strcat(a, b);

    printf("%s\n", a);
    printf("length = %zu\n", strlen(a));
    printf("compare = %d\n", strcmp("abc", "abd"));

    return 0;
}
