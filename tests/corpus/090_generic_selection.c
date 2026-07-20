#include <stdio.h>

#define TYPE_NAME(x) _Generic((x), \
    int: "int", \
    double: "double", \
    float: "float", \
    default: "other")

int main(void) {
    int i = 0;
    double x = 0.0;
    float y = 0.0f;

    printf("%s\n", TYPE_NAME(i));
    printf("%s\n", TYPE_NAME(x));
    printf("%s\n", TYPE_NAME(y));

    return 0;
}
