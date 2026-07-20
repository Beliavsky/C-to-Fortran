#include <stdio.h>

enum state {
    STATE_START,
    STATE_RUNNING,
    STATE_DONE
};

int main(void) {
    enum state state = STATE_START;
    int counter = 0;

    while (state != STATE_DONE) {
        switch (state) {
            case STATE_START:
                printf("start\n");
                state = STATE_RUNNING;
                break;

            case STATE_RUNNING:
                printf("running %d\n", counter);
                ++counter;
                if (counter == 3) {
                    state = STATE_DONE;
                }
                break;

            case STATE_DONE:
                break;
        }
    }

    printf("done\n");
    return 0;
}
