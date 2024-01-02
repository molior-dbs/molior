import asyncio
import shlex

from launchy import Launchy

from ...logger import logger
from ...molior.configuration import Configuration
from ...molior.queues import enqueue_buildtask, dequeue_buildtask, buildlog, enqueue_backend


class DockerBackend:

    def __init__(self, _):
        self.queue_amd64 = asyncio.Queue(1)
        self.queue_arm64 = asyncio.Queue(1)

        self.scheduler = {}
        cfg = Configuration("/etc/molior/backend-docker.yml")
        if not cfg:
            logger.error("docker-backend: config file not found: /etc/molior/backend-docker.yml")
        else:
            for arch in ["amd64", "arm64"]:
                self.scheduler[arch] = []
                builder = cfg.builder.get(arch)
                parallel = 1
                if builder:
                    parallel = builder.get("parallel", 1)
                for i in range(parallel):
                    self.scheduler[arch].append(asyncio.create_task(self.consumer(arch)))

    async def build(self, build_id, token, build_version, apt_server, arch, arch_any_only, distrelease_name, distrelease_version,
                    project_dist, sourcename, project_name, project_version, apt_urls, apt_keys, run_lintian):
        task_id = "build_%d" % build_id
        queue_arch = arch
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
        logger.error(f"aborting build {build_id}: NOT IMPLEMENTED")

    def get_nodes_info(self):
        return []

    async def stop(self):
        pass

    async def consumer(self, arch):
        up = True
        while up:
            try:
                task = await dequeue_buildtask(arch)
                if task is None:
                    break

                build_id = task["build_id"]

                server_url = Configuration().server.get("url")
                cfg = Configuration("/etc/molior/backend-docker.yml")
                if not cfg:
                    logger.error("docker-backend: config file not found: /etc/molior/backend-docker.yml")
                    continue

                registry = cfg.registry.get("server")
                remote_cmd = ""
                builder = cfg.builder.get(arch)
                if builder:
                    remote_cmd = builder.get("remote_cmd")

                    override_registry = builder.get("registry")
                    if override_registry is not None:
                        registry = override_registry

                cmd = shlex.split(remote_cmd)
                cmd.extend([
                    "docker", "run", "-t", "--rm",
                    "--add-host=host.docker.internal:host-gateway",
                    "-e", f"BUILD_ID={task['build_id']}",
                    "-e", f"BUILD_TOKEN={task['token']}",
                    "-e", f"PLATFORM={task['distrelease']}",
                    "-e", f"PLATFORM_VERSION={task['distversion']}",
                    "-e", f"ARCH={task['architecture']}",
                    "-e", f"ARCH_ANY_ONLY={task['arch_any_only']}",
                    "-e", f"REPO_NAME={task['repository_name']}",
                    "-e", f"VERSION={task['version']}",
                    "-e", f"PROJECT_DIST={task['project_dist']}",
                    "-e", f"PROJECT={task['project']}",
                    "-e", f"PROJECTVERSION={task['projectversion']}",
                    "-e", f"APT_SERVER={task['apt_server']}",
                    "-e", f"APT_URLS={task['apt_urls']}",
                    "-e", f"APT_KEYS={task['apt_keys']}",
                    "-e", f"RUN_LINTIAN={task['run_lintian']}",
                    "-e", f"MOLIOR_SERVER={server_url}",
                    f"{registry}/molior:{task['distversion']}-{task['architecture']}",
                    "/app/build-docker",
                    ])

                async def outh(line):
                    await buildlog(build_id, line)

                await enqueue_backend({"started": build_id})
                process = Launchy(cmd, out_handler=outh, err_handler=outh, buffered=False)
                await process.launch()
                ret = await process.wait()

                await buildlog(build_id, None)  # signal end of logs

                if not ret == 0:
                    logger.error("error running docker build")
                    await enqueue_backend({"failed": build_id})
                else:
                    await enqueue_backend({"succeeded": build_id})

            except Exception as exc:
                logger.exception(exc)

            await asyncio.sleep(1)

        logger.info("scheduler %s task terminated", arch)
