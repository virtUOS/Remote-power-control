#!/bin/sh

FAIL_COUNT=0
MAX_FAILS=6

while true; do
    if ping -c 1 -W 3 8.8.8.8 > /dev/null 2>&1; then
        FAIL_COUNT=0
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi

    if [ "$FAIL_COUNT" -ge "$MAX_FAILS" ]; then
        reboot
    fi

    sleep 10
done
