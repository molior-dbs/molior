import asyncio

from datetime import datetime
from aiofile import AIOFile, Writer
from pathlib import Path

from ..app import logger
from ..tools import get_local_tz
from ..molior.configuration import Configuration

# worker queues
task_queue = asyncio.Queue()
aptly_queue = asyncio.Queue()
notification_queue = asyncio.Queue()
backend_queue = asyncio.Queue()

# build log queues
buildlogs = {}

# buildtask queues
buildtasks = {"amd64": asyncio.Queue(), "arm64": asyncio.Queue()}


async def enqueue(queue, item):
    return await queue.put(item)


async def dequeue(queue):
    ret = await queue.get()
    queue.task_done()
    return ret


async def enqueue_task(task):
    await task_queue.put(task)


async def dequeue_task():
    return await dequeue(task_queue)


async def enqueue_aptly(task):
    await aptly_queue.put(task)


async def dequeue_aptly():
    return await dequeue(aptly_queue)


async def enqueue_notification(msg):
    await notification_queue.put(msg)


async def dequeue_notification():
    return await dequeue(notification_queue)


async def enqueue_backend(msg):
    await backend_queue.put(msg)


async def dequeue_backend():
    return await dequeue(backend_queue)


def get_log_file_path(build_id):
    buildout_path = Path(Configuration().working_dir) / "buildout"
    dir_path = buildout_path / str(build_id)
    if not dir_path.is_dir():
        try:
            dir_path.mkdir(parents=True)
        except Exception:
            return None
    full_path = dir_path / "build.log"
    return str(full_path)


async def buildlog_writer(build_id):
    filename = get_log_file_path(build_id)
    if not filename:
        logger.error("buildlog_writer: cannot get path for build %s", str(build_id))
        del buildlogs[build_id]
        return
    try:
        afp = AIOFile(filename, 'a')
        await afp.open()
        writer = Writer(afp)
        while True:
            msg = await dequeue(buildlogs[build_id])
            if msg is None:
                await enqueue_backend({"logging_done": build_id})
                continue
            elif msg is False:
                break
            await writer(msg)
            await afp.fsync()
    except Exception as exc:
        logger.exception(exc)

    del buildlogs[build_id]


async def enqueue_buildlog(build_id, msg):
    if build_id not in buildlogs:
        buildlogs[build_id] = asyncio.Queue()
        asyncio.ensure_future(buildlog_writer(build_id))
    await buildlogs[build_id].put(msg)


async def buildlogdone(build_id):
    await enqueue_buildlog(build_id, False)


async def buildlog(build_id, msg):
    await enqueue_buildlog(build_id, msg)


async def buildlogtitle(build_id, title, no_footer_newline=False, no_header_newline=True, error=False):
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

    await buildlog(build_id, msg)


async def enqueue_buildtask(arch, task):
    if arch not in buildtasks:
        return
    await enqueue(buildtasks[arch], task)


async def dequeue_buildtask(arch):
    return await dequeue(buildtasks[arch])
