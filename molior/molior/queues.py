import asyncio

from datetime import datetime
from aiofile import AIOFile, Writer
from pathlib import Path

from ..tools import get_local_tz
from ..molior.configuration import Configuration

# worker queues
task_queue = asyncio.Queue()
aptly_queue = asyncio.Queue()
notification_queue = asyncio.Queue()
backend_queue = asyncio.Queue()

# build log queues
buildlogs = {}


async def enqueue(queue, item):
    return await queue.put(item)


async def dequeue(queue):
    ret = await queue.get()
    queue.task_done()
    return ret


def enqueue_task(task):
    loop = asyncio.get_event_loop()
    asyncio.run_coroutine_threadsafe(enqueue(task_queue, task), loop)


async def dequeue_task():
    return await dequeue(task_queue)


def enqueue_aptly(task):
    loop = asyncio.get_event_loop()
    asyncio.run_coroutine_threadsafe(enqueue(aptly_queue, task), loop)


async def dequeue_aptly():
    return await dequeue(aptly_queue)


def enqueue_notification(msg):
    loop = asyncio.get_event_loop()
    asyncio.run_coroutine_threadsafe(enqueue(notification_queue, msg), loop)


async def dequeue_notification():
    return await dequeue(notification_queue)


def enqueue_backend(msg):
    loop = asyncio.get_event_loop()
    asyncio.run_coroutine_threadsafe(enqueue(backend_queue, msg), loop)


async def dequeue_backend():
    return await dequeue(backend_queue)


def get_log_file_path(build_id):
    buildout_path = Path(Configuration().working_dir) / "buildout"
    dir_path = buildout_path / str(build_id)
    if not dir_path.is_dir():
        dir_path.mkdir(parents=True)
    full_path = dir_path / "build.log"
    return str(full_path)


async def buildlog_writer(build_id):
    filename = get_log_file_path(build_id)
    afp = AIOFile(filename, 'a')
    await afp.open()
    writer = Writer(afp)
    while True:
        msg = await dequeue(buildlogs[build_id])
        if msg is None:
            enqueue_backend({"logging_done": build_id})
        elif msg is False:
            break
        await writer(msg)
        await afp.fsync()
    del buildlogs[build_id]


async def enqueue_buildlog(build_id, msg):
    if build_id not in buildlogs:
        buildlogs[build_id] = asyncio.Queue()
        asyncio.ensure_future(buildlog_writer(build_id))
    await buildlogs[build_id].put(msg)


def buildlogdone(build_id):
    loop = asyncio.get_event_loop()
    asyncio.run_coroutine_threadsafe(enqueue_buildlog(build_id, False), loop)


def buildlog(build_id, msg):
    loop = asyncio.get_event_loop()
    asyncio.run_coroutine_threadsafe(enqueue_buildlog(build_id, msg), loop)


def buildlogtitle(build_id, title, no_footer_newline=False, no_header_newline=True, error=False):
    now = get_local_tz().localize(datetime.now(), is_dst=None)
    date = datetime.strftime(now, "%a, %d %b %Y %H:%M:%S %z")

    header_newline = "\n"
    if no_header_newline:
        header_newline = ""

    footer_newline = "\n"
    if no_footer_newline:
        footer_newline = ""

    color = 36
    if error:
        color = 31

    BORDER = 80 * "+"

    msg = "{}\x1b[{}m\x1b[1m{}\x1b[0m\n".format(header_newline, color, BORDER) + \
          "\x1b[{}m\x1b[1m| molior: {:36} {} |\x1b[0m\n".format(color, title, date) + \
          "\x1b[{}m\x1b[1m{}\x1b[0m\n{}".format(color, BORDER, footer_newline)

    buildlog(build_id, msg)
