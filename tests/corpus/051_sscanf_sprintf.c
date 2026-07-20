#include <stdio.h>

int main(void) {
    const char *text = "12 3.5";
    int n;
    double x;
    char output[64];

    if (sscanf(text, "%d %lf", &n, &x) != 2) {
        return 1;
    }

    sprintf(output, "n=%d x=%.2f", n, x);
    printf("%s\n", output);

    return 0;
}
