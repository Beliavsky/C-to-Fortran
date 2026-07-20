#include <stdio.h>
#include <string.h>

int main(void) {
    int source[] = {1, 2, 3, 4};
    int destination[4];

    memset(destination, 0, sizeof(destination));
    memcpy(destination, source, sizeof(source));

    printf("%d %d %d %d\n",
           destination[0],
           destination[1],
           destination[2],
           destination[3]);

    return 0;
}
