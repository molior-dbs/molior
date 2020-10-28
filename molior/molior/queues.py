import asyncio

# worker queues
task_queue = asyncio.Queue()
aptly_queue = asyncio.Queue()
notification_queue = asyncio.Queue()
backend_queue = asyncio.Queue()


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
