"""
Weekly jobs at a fixed local time (replaces the async-cron package, which is not in Debian).

molior runs one such job: the aptly cleanup on the weekdays and at the time of the metadata entries
cleanup_weekdays (e.g. "Saturday,Sunday") and cleanup_time (e.g. "04:00").
"""
import asyncio

from datetime import datetime, timedelta

WEEKDAYS = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3, "Friday": 4, "Saturday": 5, "Sunday": 6}


def parse_time(value):
    """"HH:MM" or "HH:MM:SS" to (hour, minute, second), raises ValueError otherwise."""
    parts = value.strip().split(":")
    if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
        raise ValueError("invalid time '{}', expected HH:MM or HH:MM:SS".format(value))
    hour, minute, second = (int(p) for p in parts + ["0"] * (3 - len(parts)))
    if hour > 23 or minute > 59 or second > 59:
        raise ValueError("invalid time '{}', expected HH:MM or HH:MM:SS".format(value))
    return hour, minute, second


def next_run(now, weekdays, at):
    """
    The first time after now (exclusive) that falls on one of weekdays (0 = Monday) at the time at
    (hour, minute, second). now is a naive local datetime.
    """
    hour, minute, second = at
    for days in range(8):
        day = now + timedelta(days=days)
        run = day.replace(hour=hour, minute=minute, second=second, microsecond=0)
        if run.weekday() in weekdays and run > now:
            return run
    raise ValueError("no weekday given")


async def run_weekly(weekdays, at, job, now=datetime.now):
    """Calls job() at every next_run(); runs until cancelled."""
    last = now()
    while True:
        run = next_run(max(now(), last), weekdays, at)
        await asyncio.sleep(max((run - now()).total_seconds(), 0))
        last = run
        job()
