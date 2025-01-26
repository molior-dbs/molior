import asyncio

from contextlib import suppress
from kubernetes import client, config
from kubernetes.client.rest import ApiException


from ...logger import logger
from ...molior.configuration import Configuration
from ...molior.queues import enqueue_buildtask, dequeue_buildtask, buildlog, enqueue_backend
from ...tools import write_log_title


class KubernetesBackend:

    def __init__(self, _):
        self.queue_amd64 = asyncio.Queue(1)
        self.queue_arm64 = asyncio.Queue(1)

        self.scheduler = {}
        cfg = Configuration("/etc/molior/backend-kubernetes.yml")
        if not cfg:
            logger.error("kubernetes-backend: config file not found: /etc/molior/backend-kubernetes.yml")
        else:
            for arch in ["amd64", "arm64"]:
                self.scheduler[arch] = []
                builder = cfg.builder.get(arch)
                parallel = 1
                if builder:
                    parallel = builder.get("parallel", 1)
                logger.info(f"kubernetes backend: starting {parallel} {arch} tasks")
                for i in range(parallel):
                    self.scheduler[arch].append(asyncio.create_task(self.consumer(arch)))

        config.load_incluster_config()

    async def build(self, build_id, token, build_version, apt_server, arch, arch_any_only, distrelease_name, distrelease_version,
                    project_dist, sourcename, project_name, project_version, apt_urls, apt_keys, run_lintian):
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
        logger.error(f"aborting build {build_id}: NOT IMPLEMENTED")

    def get_nodes_info(self):
        return []

    async def stop(self):
        logger.info("stopping kubernetes backend")
        for arch in ["amd64", "arm64"]:
            for sched in self.scheduler[arch]:
                sched.cancel()
                with suppress(asyncio.CancelledError):
                    await sched

    def create_kubernetes_job(namespace, job_name, image):
        container = client.V1Container(
            name=job_name,
            image=image,
            args=["echo", "Hello, Kubernetes!"]
        )

        # Define the Pod template spec
        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels={"job-name": job_name}),
            spec=client.V1PodSpec(restart_policy="Never", containers=[container])
        )

        # Define the Job spec
        job_spec = client.V1JobSpec(
            template=template,
            # spec=V1PodSpec(
            #     node_selector={"kubernetes.io/hostname": "node-name"},  # Specify the node label here
            #     containers=[client.V1Container(name="my-container", image="nginx")]
            # ),
            backoff_limit=4  # Number of retries before failing the Job
        )

        # Define the Job resource
        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(name=job_name),
            spec=job_spec
        )

        # Create the Job in the specified namespace
        try:
            batch_v1 = client.BatchV1Api()
            batch_v1.create_namespaced_job(body=job, namespace=namespace)
            print(f"Job '{job_name}' created successfully.")
        except ApiException as e:
            print(f"Error creating Job: {e}")

    async def consumer(self, queue_arch):
        up = True
        while up:
            try:
                task = await dequeue_buildtask(queue_arch)
                if task is None:
                    break

                build_id = task["build_id"]
                arch = task['architecture']
                distversion = task['distversion']
                await enqueue_backend({"started": build_id})

                await write_log_title(build_id, "Kubernetes Build")
                await buildlog(build_id, "\x1b[36m\x1b[1mPulling build container ...\x1b[0m\n")

                server_url = Configuration().server.get("url")
                cfg = Configuration("/etc/molior/backend-kubernetes.yml")
                if not cfg:
                    logger.error("kubernetes-backend: config file not found: /etc/molior/backend-kubernetes.yml")
                    continue

                registry = cfg.registry.get("server")
                builder = cfg.builder.get(arch)

                namespace = "default"
                job_name = "example-job"
                image = f"{registry}/molior-{distversion}-{arch}"
                create_kubernetes_job(namespace, job_name, image)

                # cmd = shlex.split(remote_cmd)
                # cmd.extend([
                #     "unbuffer",
                #     "docker", "run", "-t", "--rm",
                #     "--add-host=host.docker.internal:host-gateway",
                #     "-e", f"BUILD_ID={task['build_id']}",
                #     "-e", f"BUILD_TOKEN={task['token']}",
                #     "-e", f"PLATFORM={task['distrelease']}",
                #     "-e", f"PLATFORM_VERSION={distversion}",
                #     "-e", f"ARCH={arch}",
                #     "-e", f"ARCH_ANY_ONLY={task['arch_any_only']}",
                #     "-e", f"REPO_NAME={task['repository_name']}",
                #     "-e", f"VERSION={task['version']}",
                #     "-e", f"PROJECT_DIST={task['project_dist']}",
                #     "-e", f"PROJECT={task['project']}",
                #     "-e", f"PROJECTVERSION={task['projectversion']}",
                #     "-e", f"APT_SERVER={task['apt_server']}",
                #     "-e", f"APT_KEYS={' '.join(task['apt_keys'])}",
                #     "-e", f"RUN_LINTIAN={task['run_lintian']}",
                #     "-e", f"MOLIOR_SERVER={server_url}",
                #     f"{registry}/molior-{distversion}-{arch}",
                #     "/app/docker-build",
                #     ])

                # has_output = False

                # async def outh(line):
                #     nonlocal has_output
                #     has_output = True
                #     await buildlog(build_id, line)

                # pull_cmd = shlex.split(remote_cmd)
                # pull_cmd.extend(shlex.split(f"unbuffer docker pull {registry}/molior-{distversion}-{arch}"))
                # process = Launchy(pull_cmd, out_handler=outh, err_handler=outh, buffered=False)
                # await process.launch()
                # ret = await process.wait()

                # if not ret == 0 and not has_output:
                #     await buildlog(build_id, f"E: error pulling docker build image {registry}/molior-{distversion}-{arch}")
                #     await enqueue_backend({"failed": build_id})

                # else:
                #     await buildlog(build_id, "\n")

                #     process = Launchy(cmd, out_handler=outh, err_handler=outh, buffered=False)
                #     await process.launch()
                #     ret = await process.wait()

                #     if not ret == 0:
                #         await buildlog(build_id, f"E: error running docker command {shlex.join(cmd)}\n")
                #         await enqueue_backend({"failed": build_id})
                #     else:
                #         await enqueue_backend({"succeeded": build_id})

                await buildlog(build_id, None)  # signal end of logs

            except Exception as exc:
                logger.exception(exc)

            await asyncio.sleep(1)

        logger.info("scheduler %s task terminated", queue_arch)
