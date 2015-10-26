#!/usr/bin/python

#from deluge.log import LOG as log
from deluge.ui.client import client
import deluge.component as component
from twisted.internet import reactor, defer
import time
import datetime
import logging
from urlparse import urlparse
import argparse

# Logging
log = logging.getLogger("core")
logger = logging.getLogger()
handler = logging.StreamHandler()
FORMAT = "%(asctime)-15s %(levelname)-8s %(name)-11s %(message)s"
formatter = logging.Formatter(FORMAT)
handler.setFormatter(formatter)
logger.addHandler(handler)

status_keys = ["state",
               "save_path",
               "tracker",
               "tracker_status",
               "next_announce",
               "name",
               "total_size",
               "progress",
               "num_seeds",
               "total_seeds",
               "num_peers",
               "total_peers",
               "eta",
               "download_payload_rate",
               "upload_payload_rate",
               "ratio",
               "distributed_copies",
               "num_pieces",
               "piece_length",
               "total_done",
               "files",
               "file_priorities",
               "file_progress",
               "peers",
               "is_seed",
               "is_finished",
               "active_time",
               "seeding_time",
               "time_added"
               ]

non_fatal_errors = ["timed out", "Connection timed out", "Announce OK"]

count = 0
torrent_ids = []

# CONFIGURATION
maxlimits = {'bitmetv.org': 50,
             'tvtorrents.com': 50}

max_ratio = 10
orphan_limit = 5
free_space_limit = 5

def endSession(esresult):
    if esresult:
        print esresult
        reactor.stop()
    else:
        client.disconnect()
        log.debug("Client disconnected.")
        reactor.stop()

def printReport(rresult):
    log.debug("TOTAL TORRENTS: %i" % (count))
    endSession(None)


def print_info(status):
    print("--State: %s" % (status["state"]))
    print("--Added: %s" % (time.ctime(status["time_added"])))
    added = datetime.datetime.fromtimestamp(status["time_added"])
    td = datetime.datetime.now() - added
    hours, minutes, seconds = td.seconds // 3600, td.seconds // 60 % 60, td.seconds % 60
    print("--Age: %dd %dh %dm %ds" % (td.days, hours, minutes, seconds))
    print("--Ratio: %s" % (status["ratio"]))
    print("--Tracker: %s" % (status["tracker"]))

def log_removal(status, reason=None):
    print("Added for removal: %s" % (status["name"]))
    if reason:
        print("--Reason: %s" % reason)
    else:
        print("--Reason: %s" % (status["tracker_status"]))
    print_info(status)

def on_torrents_status(all_torrents):
    global filtertime
    tlist=[]

    torrents_by_tracker = {}

    # order torrents by tracker
    for torrent_id, status in all_torrents.items():
        if status['tracker']:
            tracker = urlparse(status['tracker']).hostname
        else:
            tracker = "No tracker"

        torrents_by_tracker.setdefault(tracker, []).append((torrent_id, status))

    if log.getEffectiveLevel() == logging.getLevelName("DEBUG"):
        log.debug("Tracker torrent counts:")
        for tracker, torrents in torrents_by_tracker.items():
            log.debug("%-25s count: %d", tracker, len(torrents))

    total_delete_count = 0

    # Delete errored torrents (mostly not registered)
    for tracker, torrents in torrents_by_tracker.items():
        for torrent_id, status in torrents:
            # messages are of format
            # <tracker name>: <message>
            tracker, message = status["tracker_status"].split(': ', 1)
            if message not in non_fatal_errors:
                if message == "Error: torrent not registered with this tracker":
                    tlist.append(client.core.remove_torrent(torrent_id, True))
                    log_removal(status, "Torrent not registered with tracker")

    # Delete oldest torrents from sites with max count reached
    if args['delete_maxcount']:
        # go through sites with set maximum linits
        for tracker, limit in maxlimits.items():
            limit_count = 0
            # count number of torrents on tracker
            for torrent_id, status in all_torrents.items():
                if tracker in status['tracker']:
                    limit_count += 1

            log.debug("%d torrents found for tracker %s (limit %d)" % (limit_count, tracker, limit))

            # over or at limit, start deleting
            if limit_count >= limit:
                # delete up to limit + 1 to make room
                delete_count = limit_count - limit
                delete_count += 1

                if is_interactive:
                    print("Tracker %s is %d over limit" % (tracker, delete_count))
                    print("Deleting %d oldest torrents to make room" % delete_count)

                # start deleting from the oldest onwards
                for torrent_id, status in sorted(all_torrents.items(), key=lambda item: item[1]["time_added"]):
                    if tracker in status['tracker']:
                        tlist.append(client.core.remove_torrent(torrent_id, True))

                        delete_count = delete_count - 1
                        total_delete_count += 1

                        if is_interactive:
                            log_removal(status, "tracker %s over limit" % tracker)
                        if delete_count <= 0:
                            break


    # Remove torrents with no tracker
    if args['delete_orphans']:
        counter = 0
        for torrent_id, status in torrents_by_tracker.get("No tracker", []):
            # Don't count timed out trackers as no tracker torrents
            # this happens f.ex. when deluge is started with a big torrent load,
            # not all torrents can connect in time
            if not any(reason in status["tracker_status"] for reason in non_fatal_errors):
                added = datetime.datetime.fromtimestamp(status["time_added"])
                td = datetime.datetime.now() - added
                hours, minutes, seconds = td.seconds // 3600, td.seconds // 60 % 60, td.seconds % 60
                # don't delete torrents under 1d old as orphans, it might be a connection issue
                if td.days < 1:
                    if is_interactive:
                        print("Skipping %s" % status["name"])
                        print("Reason: under 1d old")
                        print_info(status)
                    continue
                tlist.append(client.core.remove_torrent(torrent_id, True))
                total_delete_count +=1
                log_removal(status, "Orphan torrent")
                counter += 1
            # Max 5 at a time
            if counter > orphan_limit: break

    # delete torrents over maximum ratio
    if args['maximum_ratio']:
        for torrent_id, status in sorted(all_torrents.items(), key=lambda item: item[1]["ratio"]):
            if status['ratio'] > max_ratio:
                total_delete_count +=1
                tlist.append(client.core.remove_torrent(torrent_id, True))
                log_removal(status, "Torrent over maximum ratio (%d)" % max_ratio)

    # Only delete oldest to free space if nothing else has been deleted during this run
    # The free space is determined before the run, so this is necessary
    if total_delete_count == 0 and args['free_space']:
        counter = 0
        for torrent_id, status in sorted(all_torrents.items(), key=lambda item: item[1]["time_added"]):
            tlist.append(client.core.remove_torrent(torrent_id, True))
            if is_interactive:
                log_removal(status, "Free disk space needed")
            counter += 1
            if counter >= free_space_limit: break

    # for torrent_id, status in all_torrents.items():
    #     # Filter out torrents with no issues
    #     if status["tracker_status"].endswith("Announce OKXX"):
    #         log.debug("Current torrent id is: %s" % (torrent_id))
    #         log.debug("--Torrent name is: %s" % (status["name"]))
    #         log.debug("--Torrent state is: %s" % (status["state"]))
    #         log.debug("--Torrent ratio is: %s" % (status["ratio"]))
    #         log.debug("--Torrent DL rate is: %s" % (status["download_payload_rate"]))
    #         log.debug("--Torrent UL rate is: %s" % (status["upload_payload_rate"]))
    #         log.debug("--Torrent tracker is: %s" % (status["tracker_status"]))

    global count
    count = len(all_torrents)

    defer.DeferredList(tlist).addCallback(printReport)

def on_session_state(result):
    client.core.get_torrents_status({"id": result}, status_keys).addCallback(on_torrents_status)

def on_connect_success(result):
    log.debug("Connection was successful!")
    curtime = time.time()
    log.debug("Current unix time is %i" % (curtime))
    # connected, start querying session state
    client.core.get_session_state().addCallback(on_session_state)


if __name__ == "__main__":
    global args

    parser = argparse.ArgumentParser(description="Automated Deluge Manager")
    parser.add_argument("--delete-orphans", action="store_true")
    parser.add_argument("--delete-maxcount", action="store_true")
    parser.add_argument("--free-space", action="store_true")
    parser.add_argument("--maximum-ratio", action="store_true")
    parser.add_argument("--cron", action="store_false")

    parsed_args = parser.parse_args()

    args = vars(parsed_args)

    cliconnect = client.connect()
    is_interactive = args['cron']

    # turn on logging if running interactively
    if is_interactive:
        print("running interactively")
        log.setLevel(logging.DEBUG)

    cliconnect.addCallbacks(on_connect_success, endSession, errbackArgs=("Connection failed: check settings and try again."))

    reactor.run()
