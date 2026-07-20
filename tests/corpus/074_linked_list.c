#include <stdio.h>
#include <stdlib.h>

struct node {
    int value;
    struct node *next;
};

int main(void) {
    struct node *head = NULL;
    int i;

    for (i = 1; i <= 5; ++i) {
        struct node *new_node = malloc(sizeof(*new_node));

        if (new_node == NULL) {
            return 1;
        }

        new_node->value = i * 10;
        new_node->next = head;
        head = new_node;
    }

    while (head != NULL) {
        struct node *next = head->next;
        printf("%d\n", head->value);
        free(head);
        head = next;
    }

    return 0;
}
