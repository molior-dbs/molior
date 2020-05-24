import asyncio

# worker queues
task_queue = asyncio.Queue()
aptly_queue = asyncio.Queue()
notification_queue = asyncio.Queue()
