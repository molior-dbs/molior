"""Weekly jobs (molior/cron.py), used for the aptly cleanup."""
import asyncio

from datetime import datetime

import pytest

from molior.cron import WEEKDAYS, parse_time, next_run, run_weekly

SATURDAY, SUNDAY, MONDAY = WEEKDAYS["Saturday"], WEEKDAYS["Sunday"], WEEKDAYS["Monday"]


@pytest.mark.parametrize("value,expected", [
    ("04:00", (4, 0, 0)),
    ("4:05", (4, 5, 0)),
    (" 23:59:59 ", (23, 59, 59)),
])
def test_parse_time(value, expected):
    assert parse_time(value) == expected


@pytest.mark.parametrize("value", ["", "4", "24:00", "04:60", "04:00:60", "4h", "04:00:00:00", "-1:00"])
def test_parse_time_invalid(value):
    with pytest.raises(ValueError):
        parse_time(value)


def test_next_run_later_today():
    # 2026-01-03 is a Saturday
    assert next_run(datetime(2026, 1, 3, 3, 0), {SATURDAY}, (4, 0, 0)) == datetime(2026, 1, 3, 4, 0)


def test_next_run_is_after_now():
    assert next_run(datetime(2026, 1, 3, 4, 0), {SATURDAY}, (4, 0, 0)) == datetime(2026, 1, 10, 4, 0)


def test_next_run_next_weekday():
    assert next_run(datetime(2026, 1, 3, 5, 0), {SATURDAY, SUNDAY}, (4, 0, 0)) == datetime(2026, 1, 4, 4, 0)


def test_next_run_over_month_end():
    # 2026-01-30 is a Friday
    assert next_run(datetime(2026, 1, 30, 12, 0), {MONDAY}, (4, 0, 0)) == datetime(2026, 2, 2, 4, 0)


def test_next_run_needs_a_weekday():
    with pytest.raises(ValueError):
        next_run(datetime(2026, 1, 3), set(), (4, 0, 0))


def test_run_weekly_calls_the_job_once_per_run(monkeypatch):
    clock = [datetime(2026, 1, 3, 3, 59, 59)]
    sleeps = []
    calls = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        # wake up a bit early, the job must still run once and not again for the same slot
        clock[0] = datetime(2026, 1, 3, 3, 59, 59, 900000) if len(sleeps) == 1 else datetime(2026, 1, 10, 4, 0)
        if len(sleeps) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_weekly({SATURDAY}, (4, 0, 0), lambda: calls.append(clock[0]), now=lambda: clock[0]))
    assert sleeps[0] == 1
    assert len(calls) == 2
    assert sleeps[1] == pytest.approx(7 * 24 * 3600 + 0.1)
