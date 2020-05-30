#!/bin/sh

LOCKFILE=/tmp/delugemanager_lock.txt
if [ -e ${LOCKFILE} ] && kill -0 `cat ${LOCKFILE}`; then
    echo "already running"

    # Get lock file age in seconds
    AGE=$(($(date +%s) - $(date +%s -r ${LOCKFILE})))
    echo "Lock file age $AGE"
    if [ "$AGE" -gt "300" ]
    then
      echo "Lock file too old, removing manually"
      rm -f ${LOCKFILE}
    fi

    exit
fi

# make sure the lockfile is removed when we exit and then claim it
trap "rm -f ${LOCKFILE}; exit" INT TERM EXIT
echo $$ > ${LOCKFILE}

# Don't run if deluge has been running for less than 30 minutes
# or the script might delete torrents that are still rehashing -> orphans -> deleted
DELUGE_UPTIME=$(ps -eo pid,etimes | grep $(pidof -x /usr/bin/deluged) | awk '{print $2}')

if [ "$DELUGE_UPTIME" -lt "1800" ]
then
  echo "Waiting for Deluge startup"
  exit 0
fi

# volume where downloads are stored
VOLUME="/dev/root"

DISKFREE=$(df $VOLUME | tail -1 | awk '{print $4}')

MANAGER_ARGS="--cron --delete-maxcount --delete-orphans"

# Under 30 GB, ask manager for free disk space
if [ "$DISKFREE" -lt "30000000" ]
then
    echo "Free disk space needed"
    MANAGER_ARGS="$MANAGER_ARGS --free-space"

    python3 $(dirname $0)/delugemanager.py $MANAGER_ARGS
fi


rm -f ${LOCKFILE}
