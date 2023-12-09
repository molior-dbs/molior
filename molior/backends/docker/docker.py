import asyncio
from launchy import Launchy

from ...logger import logger
# from ...molior.configuration import Configuration
from ...molior.queues import enqueue_buildtask, dequeue_buildtask, buildlog, enqueue_backend


class DockerBackend:

    def __init__(self, loop):
        self.loop = loop
        self.task_scheduler_amd64 = asyncio.ensure_future(self.scheduler(), loop=self.loop)

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

    async def stop(self):
        pass

    async def scheduler(self):
        up = True
        while up:
            try:
                arch = "amd64"
                task = await dequeue_buildtask(arch)
                if task is None:
                    break

                build_id = task["build_id"]

                await enqueue_backend({"started": build_id})

                async def outh(line):
                    logger.info(f"{build_id}: {line}")
                    await buildlog(build_id, f"{line}")

                process = Launchy(["docker", "run", "-t", "--add-host=host.docker.internal:host-gateway",
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
                                   "-e", f"MOLIOR_SERVER=http://host.docker.internal:8000",
                                   f"localhost:5000/molior:{task['distversion']}", "/app/build-docker",
                                   ], outh, outh)
                await process.launch()
                ret = await process.wait()

                await buildlog(build_id, None)  # signal end of logs

                if not ret == 0:
                    logger.error("error starting docker build")
                    await enqueue_backend({"failed": build_id})
                else:
                    await enqueue_backend({"succeeded": build_id})

            except Exception as exc:
                logger.exception(exc)

            await asyncio.sleep(1)

        logger.info("scheduler %s task terminated", arch)
