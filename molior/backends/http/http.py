import asyncio
import json

from concurrent.futures._base import CancelledError

from ...app import app, logger
from ...molior.configuration import Configuration
from ...molior.queues import enqueue_backend, enqueue_buildtask, dequeue_buildtask
from ...molior.notifier import Subject, Event, notify


registry = {"amd64": [], "arm64": []}
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
            # stop if disconnected
            if ws_client not in registry[arch] and ws_client not in running_nodes[arch]:
                break

            # was pong recieved ?
            if hasattr(ws_client, "molior_pong_pending") and ws_client.molior_pong_pending == 1:
                logger.warning("backend: ping timeout after %ds on %s/%s",
                               PING_TIMEOUT, ws_client.molior_node_arch, ws_client.molior_node_name)
                await deregister_node(ws_client)
                # await ws_client.close()
                break

            # send ping
            ws_client.molior_pong_pending = 1
            if asyncio.iscoroutinefunction(ws_client.send_str):
                await ws_client.send_str(json.dumps({"ping": 1}))
            else:
                ws_client.send_str(json.dumps({"ping": 1}))

            # wait for pong
            try:
                await asyncio.sleep(PING_TIMEOUT)
            except CancelledError:
                break

    except Exception as exc:
        logger.exception(exc)
        # await ws_client.close()


@app.websocket_connect(group="registry")
async def node_register(ws_client):
    node = ws_client.cirrina.request.match_info["node"]
    arch = ws_client.cirrina.request.match_info["arch"]

    if arch not in registry:
        logger.error("backend: invalid architecture received: '%s'", arch)
        # await ws_client.close()
        return ws_client

    # initialize
    ws_client.molior_node_name = node
    ws_client.molior_node_arch = arch
    ws_client.molior_cpu_cores = 0
    ws_client.molior_load = 0
    ws_client.molior_ram_total = 0
    ws_client.molior_disk_total = 0
    ws_client.molior_nodeid = ""
    ws_client.molior_ip = ""
    ws_client.molior_client_ver = ""
    ws_client.molior_ram_used = 0
    ws_client.molior_disk_used = 0
    ws_client.molior_sourcename = ""
    ws_client.molior_sourceversion = ""
    ws_client.molior_sourcearch = ""
    ws_client.molior_uptime_seconds = 0

    registry[arch].insert(0, ws_client)
    logger.info("backend: %s node registered: %s", arch, node)
    ws_client.molior_watchdog = asyncio.ensure_future(watchdog(ws_client))
    await enqueue_backend({"node_registered": 1})


@app.websocket_message("/internal/registry/{arch}/{node}",
                       group="registry", authenticated=False)
async def node_message(ws_client, msg):
    try:
        status = json.loads(msg)
        if "register" in status:
            ws_client.molior_cpu_cores = status["register"].get("cpu_cores")
            ws_client.molior_ram_total = status["register"].get("ram_total")
            ws_client.molior_disk_total = status["register"].get("disk_total")
            ws_client.molior_nodeid = status["register"].get("id")
            ws_client.molior_ip = status["register"].get("ip")
            ws_client.molior_client_ver = status["register"].get("client_ver")
            return

        if "pong" in status:
            ws_client.molior_pong_pending = 0
            ws_client.molior_uptime_seconds = status["pong"]["uptime_seconds"]
            ws_client.molior_load = status["pong"]["load"]
            ws_client.molior_ram_used = status["pong"].get("ram_used")
            ws_client.molior_disk_used = status["pong"].get("disk_used")
            return

        arch = ws_client.molior_node_arch
        build_id = ws_client.molior_build_id

        if status["status"] == "building":
            await enqueue_backend({"started": build_id})

        elif status["status"] == "failed":
            await enqueue_backend({"failed": build_id})
            if ws_client in running_nodes[arch]:
                running_nodes[arch].remove(ws_client)
                registry[arch].insert(0, ws_client)
            ws_client.molior_build_id = None
            ws_client.molior_sourcename = ""
            ws_client.molior_sourceversion = ""
            ws_client.molior_sourcearch = ""

        elif status["status"] == "success":
            logger.debug("node: finished build {}".format(build_id))
            await enqueue_backend({"succeeded": build_id})
            if ws_client in running_nodes[arch]:
                running_nodes[arch].remove(ws_client)
                registry[arch].insert(0, ws_client)
            ws_client.molior_build_id = None
            ws_client.molior_sourcename = ""
            ws_client.molior_sourceversion = ""
            ws_client.molior_sourcearch = ""

        else:
            logger.error("backend: invalid message received: '%s'", status["status"])

    except Exception as exc:
        logger.exception(exc)


@app.websocket_disconnect(group="registry")
async def node_disconnected(ws_client):
    await deregister_node(ws_client)


async def deregister_node(ws_client):
    node = ws_client.molior_node_name
    arch = ws_client.molior_node_arch

    if ws_client in registry[arch]:
        registry[arch].remove(ws_client)
        logger.warning("backend: node disconnected: %s/%s", arch, node)

    elif ws_client in running_nodes[arch]:
        running_nodes[arch].remove(ws_client)
        build_id = ws_client.molior_build_id
        logger.error("backend: lost build_%d on %s/%s", build_id, arch, node)
        await enqueue_backend({"failed": build_id})

    else:
        logger.warning("backend: unknown node disconnect: %s/%s", arch, node)

    await ws_client.molior_watchdog


class HTTPBackend:
    """
    This is the default backend, using HTTP and WebSockets.
    """

    def __init__(self, loop):
        self.loop = loop
        self.task_scheduler_amd64 = asyncio.ensure_future(self.scheduler("amd64"), loop=self.loop)
        self.task_scheduler_arm64 = asyncio.ensure_future(self.scheduler("arm64"), loop=self.loop)
        self.task_notifier = asyncio.ensure_future(self.notifier(), loop=self.loop)

    async def build(self, build_id, token, build_version, apt_server, arch, arch_any_only, distrelease_name, distrelease_version,
                    project_dist, sourcename, project_name, project_version, apt_urls, apt_keys, run_lintian=True):
        task_id = "build_%d" % build_id
        if arch == "i386" or arch == "amd64":
            queue_arch = "amd64"
        elif arch == "armhf" or arch == "arm64":
            queue_arch = "arm64"
        else:
            logger.error("backend: invalid build architecture '%s'", arch)
            return False

        await enqueue_buildtask(queue_arch, {"build_id": build_id,
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
                                             "apt_keys": apt_keys,
                                             "task_id": task_id,
                                             "run_lintian": run_lintian})

    async def abort(self, build_id):
        logger.error(f"aborting build {build_id}")
        for arch in running_nodes:
            for node in running_nodes[arch]:
                if node.molior_build_id == build_id:
                    logger.error(f"aborting build {build_id} on node {node.molior_node_name}")
                    await node.send_str(json.dumps({"abort": build_id}))
                    return
        logger.error(f"Error aborting build {build_id}: no node found")

    def get_nodes_info(self):
        # FIXME: lock both dicts on every access
        build_nodes = []
        for arch in registry:
            for node in registry[arch]:
                build_nodes.append({
                    "name": node.molior_node_name,
                    "arch": arch,
                    "state": "idle",
                    "uptime_seconds": node.molior_uptime_seconds,
                    "load": node.molior_load,
                    "cpu_cores": node.molior_cpu_cores,
                    "ram_used": node.molior_ram_used,
                    "ram_total": node.molior_ram_total,
                    "disk_used": node.molior_disk_used,
                    "disk_total": node.molior_disk_total,
                    "id": node.molior_nodeid,
                    "ip": node.molior_ip,
                    "client_ver": node.molior_client_ver,
                    "sourcename": node.molior_sourcename,
                    "sourceversion": node.molior_sourceversion,
                    "sourcearch": node.molior_sourcearch
                })
        for arch in running_nodes:
            for node in running_nodes[arch]:
                build_nodes.append({
                    "name": node.molior_node_name,
                    "arch": arch,
                    "state": "busy",
                    "uptime_seconds": node.molior_uptime_seconds,
                    "load": node.molior_load,
                    "cpu_cores": node.molior_cpu_cores,
                    "ram_used": node.molior_ram_used,
                    "ram_total": node.molior_ram_total,
                    "disk_used": node.molior_disk_used,
                    "disk_total": node.molior_disk_total,
                    "id": node.molior_nodeid,
                    "ip": node.molior_ip,
                    "client_ver": node.molior_client_ver,
                    "sourcename": node.molior_sourcename,
                    "sourceversion": node.molior_sourceversion,
                    "sourcearch": node.molior_sourcearch
                })
        return build_nodes

    async def stop(self):
        self.task_scheduler_amd64.cancel()
        await self.task_scheduler_amd64
        self.task_scheduler_arm64.cancel()
        await self.task_scheduler_arm64
        self.task_notifier.cancel()
        await self.task_notifier

        for arch in registry.keys():
            for node in registry[arch]:
                await deregister_node(node)

    async def scheduler(self, arch):
        while True:
            try:
                task = await dequeue_buildtask(arch)
                if task is None:
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
                logger.info("build-%d: building for %s on %s ", build_id, arch, node.molior_node_name)
                node.molior_build_id = build_id
                node.molior_sourcename = task.get("repository_name")
                node.molior_sourceversion = task.get("version")
                node.molior_sourcearch = task.get("architecture")
                await node.send_str(json.dumps({"task": task}))

            except Exception as exc:
                logger.exception(exc)

            await asyncio.sleep(1)

        logger.info("scheduler %s task terminated", arch)

    async def notifier(self):
        while True:
            nodes = []
            for arch in registry:
                nodes.extend(registry[arch])
            for arch in running_nodes:
                nodes.extend(running_nodes[arch])

            data = []
            for node in nodes:
                data.append({
                    "id": node.molior_nodeid,
                    "state": "busy" if node in running_nodes["amd64"] or node in running_nodes["arm64"] else "idle",
                    "uptime_seconds": node.molior_uptime_seconds,
                    "load": node.molior_load,
                    "ram_used": node.molior_ram_used,
                    "disk_used": node.molior_disk_used,
                    "sourcename": node.molior_sourcename,
                    "sourceversion": node.molior_sourceversion,
                    "sourcearch": node.molior_sourcearch
                    })
            await notify(Subject.node.value, Event.changed.value, data)
            try:
                await asyncio.sleep(4)
            except Exception:
                break
        logger.info("notifier task terminated")
