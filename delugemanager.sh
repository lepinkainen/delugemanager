#!/bin/sh
DISKFREE=$(df | grep /dev/sda2 | awk '{print $4}')

MANAGER_ARGS="--cron --delete-maxcount --delete-orphans --maximum-ratio"

# Under 25 GB, ask manager for free disk space
if [ "$DISKFREE" -lt "25000000" ]
then
    MANAGER_ARGS="$MANAGER_ARGS --free-space"
fi

python $(dirname $0)/delugemanager.py $MANAGER_ARGS
