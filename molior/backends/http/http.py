import asyncio
import json

from molior.app import app, logger
from molior.molior.worker_backend import backend_queue
from molior.molior.configuration import Configuration

registry = {"amd64": [], "arm64": []}
build_tasks = {"amd64": asyncio.Queue(), "arm64": asyncio.Queue()}
running_nodes = {"amd64": [], "arm64": []}

cfg = Configuration()
pt = cfg.backend_http.get("ping_timeout")
if pt:
    PING_TIMEOUT = int(pt)
else:
    PING_TIMEOUT = 5


async def watchdog(ws_client):
    try:
        arch = ws_client.molior_node_arch
        while True:
            if hasattr(ws_client, "molior_pong_pending") and ws_client.molior_pong_pending == 1:
                logger.info("backend: ping timeout after %ds on %s/%s",
                            PING_TIMEOUT, ws_client.molior_node_arch, ws_client.molior_node_name)
                await node_disconnected(ws_client)
                await ws_client.close()
                break
            ws_client.molior_pong_pending = 1
            if asyncio.iscoroutinefunction(ws_client.send_str):
                await ws_client.send_str(json.dumps({"ping": 1}))
            else:
                ws_client.send_str(json.dumps({"ping": 1}))
            await asyncio.sleep(PING_TIMEOUT)
            if ws_client not in registry[arch] and ws_client not in running_nodes[arch]:
                break
    except Exception as exc:
        logger.exception(exc)
        await ws_client.close()


@app.websocket_connect(group="registry")
async def node_register(ws_client):
    node = ws_client.cirrina.request.match_info["node"]
    arch = ws_client.cirrina.request.match_info["arch"]
    ws_client.molior_node_name = node
    ws_client.molior_node_arch = arch
    if arch in registry:
        registry[arch].insert(0, ws_client)
        logger.info("backend: node registered: %s/%s", arch, node)
        asyncio.ensure_future(watchdog(ws_client))
        await backend_queue.put({"node_registered": 1})
    else:
        logger.error("backend: invalid architecture received: '%s'", arch)


@app.websocket_message("/internal/registry/{arch}/{node}", group="registry", authenticated=False)
async def node_message(ws_client, msg):
    try:
        status = json.loads(msg)
        if "pong" in status:
            ws_client.molior_pong_pending = 0
            ws_client.molior_uptime_seconds = status["pong"]["uptime_seconds"]
            ws_client.molior_load = status["pong"]["load"]
            return

        arch = ws_client.molior_node_arch
        build_id = ws_client.molior_build_id

        if status["status"] == "building":
            await backend_queue.put({"started": build_id})

        elif status["status"] == "failed":
            await backend_queue.put({"failed": build_id})
            if ws_client in running_nodes[arch]:
                running_nodes[arch].remove(ws_client)
                registry[arch].insert(0, ws_client)
            ws_client.molior_build_id = None

        elif status["status"] == "success":
            await backend_queue.put({"succeeded": build_id})
            if ws_client in running_nodes[arch]:
                running_nodes[arch].remove(ws_client)
                registry[arch].insert(0, ws_client)
            ws_client.molior_build_id = None

        else:
            logger.error("backend: invalid message received: '%s'", status["status"])

    except Exception as exc:
        logger.exception(exc)


@app.websocket_disconnect(group="registry")
async def node_disconnected(ws_client):
    node = ws_client.molior_node_name
    arch = ws_client.molior_node_arch

    if ws_client in registry[arch]:
        registry[arch].remove(ws_client)
        logger.info("backend: node disconnected: %s/%s", arch, node)

    elif ws_client in running_nodes[arch]:
        running_nodes[arch].remove(ws_client)
        build_id = ws_client.molior_build_id
        logger.error("backend: lost build_%d on %s/%s", build_id, arch, node)
        await backend_queue.put({"failed": build_id})

    else:
        logger.error("backend: unknown node disconnect: %s/%s", arch, node)


class HTTPBackend:
    """
    This is the default backend, using HTTP and WebSockets.
    """

    def __init__(self, bq, loop):
        self.backend_queue = bq
        self.loop = loop
        asyncio.ensure_future(self.scheduler("amd64"), loop=self.loop)
        asyncio.ensure_future(self.scheduler("arm64"), loop=self.loop)

    def build(self, build_id, token, build_version, apt_server, arch, arch_any_only, distrelease_name, distrelease_version,
              project_dist, sourcename, project_name, project_version, apt_urls):
        task_id = "build_%d" % build_id
        if arch == "i386" or arch == "amd64":
            queue_arch = "amd64"
        elif arch == "armhf" or arch == "arm64":
            queue_arch = "arm64"
        else:
            logger.error("backend: invalid build architecture '%s'", arch)
            return False

        async def queueup():
            await build_tasks[queue_arch].put(
                {
                    "build_id": build_id,
                    "token": token,
                    "version": build_version,
                    "apt_server": apt_server,
                    "architecture": arch,
                    "arch_any_only": arch_any_only,
                    "distrelease": distrelease_name,
                    "distversion": distrelease_version,
                    "project_dist": project_dist,
                    "repository_name": sourcename,
                    "project": project_name,
                    "projectversion": project_version,
                    "apt_urls": apt_urls,
                    "task_id": task_id,
                }
            )

        asyncio.ensure_future(queueup(), loop=self.loop)

    def get_nodes_info(self):
        # FIXME: lock both dicts on every access
        build_nodes = {}
        for arch in registry:
            for node in registry[arch]:
                build_nodes[node.molior_node_name] = {
                    "arch": arch,
                    "state": "idle",
                    "uptime_seconds": node.molior_uptime_seconds,
                    "load": node.molior_load,
                }
        for arch in running_nodes:
            for node in running_nodes[arch]:
                build_nodes[node.molior_node_name] = {
                    "arch": arch,
                    "state": "busy",
                    "uptime_seconds": node.molior_uptime_seconds,
                    "load": node.molior_load,
                }
        return build_nodes

    async def scheduler(self, arch):
        while True:
            try:
                task = await build_tasks[arch].get()
                if task is None:
                    logger.info("backend: got emtpy task, aborting...")
                    break

                build_id = task["build_id"]

                while True:
                    try:
                        node = registry[arch].pop()
                    except IndexError:
                        # FIXME: put task to top of the queue / pending queue
                        await asyncio.sleep(1)
                        continue
                    break
                running_nodes[arch].append(node)
                logger.info("backend: build_%d assigned to %s/%s ", build_id, arch, node.molior_node_name)
                node.molior_build_id = build_id
                if asyncio.iscoroutinefunction(node.send_str):
                    await node.send_str(json.dumps({"task": task}))
                else:
                    node.send_str(json.dumps({"task": task}))
                build_tasks[arch].task_done()

            except Exception as exc:
                logger.exception(exc)

            await asyncio.sleep(1)
