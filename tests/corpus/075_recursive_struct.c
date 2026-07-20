#include <stdio.h>

struct tree_node {
    int value;
    struct tree_node *left;
    struct tree_node *right;
};

int tree_sum(const struct tree_node *node) {
    if (node == NULL) {
        return 0;
    }

    return node->value + tree_sum(node->left) + tree_sum(node->right);
}

int main(void) {
    struct tree_node a = {1, NULL, NULL};
    struct tree_node b = {2, NULL, NULL};
    struct tree_node root = {3, &a, &b};

    printf("%d\n", tree_sum(&root));
    return 0;
}
