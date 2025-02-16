import asyncio
import concurrent
import time

from contextlib import suppress
from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException

from ...logger import logger
from ...molior.configuration import Configuration
from ...molior.queues import enqueue_buildtask, dequeue_buildtask, buildlog, enqueue_backend, enqueue_buildlog_nowait
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

    def create_kubernetes_job(self, namespace, job_name, image, envvars):
        container = client.V1Container(
            name=job_name,
            image=image,
            env=[client.V1EnvVar(name=en, value=str(ev)) for en, ev in envvars],
            args=["/app/docker-build"]
        )

        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels={"job-name": job_name}),
            spec=client.V1PodSpec(restart_policy="Never", containers=[container])
        )

        job_spec = client.V1JobSpec(template=template)

        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(name=job_name),
            spec=job_spec
        )

        try:
            batch_v1 = client.BatchV1Api()
            batch_v1.create_namespaced_job(body=job, namespace=namespace)
            return True
        except ApiException as e:
            logger.error(f"Error creating Job: {e}")
        return False

    def monitor_job_status(self, job_name, namespace):
        w = watch.Watch()
        batch_v1 = client.BatchV1Api()
        for event in w.stream(batch_v1.list_namespaced_job, namespace=namespace):
            job = event["object"]
            if job.metadata.name == job_name:
                status = job.status
                if status.succeeded:
                    w.stop()
                    return True
                elif status.failed:
                    w.stop()
        return False

    def stream_pod_logs(self, loop, build_id, job_name, namespace):
        core_v1 = client.CoreV1Api()
        pod_name = None
        for i in range(300):
            pod_list = core_v1.list_namespaced_pod(namespace=namespace, label_selector=f"job-name={job_name}")
            if not pod_list.items:
                time.sleep(1)
                continue
            pod_name = pod_list.items[0].metadata.name

        if not pod_name:
            logger.error(f"No pods found for Job {job_name}")
            return False

        phase = None
        for i in range(300):
            pod_status = core_v1.read_namespaced_pod_status(name=pod_name, namespace=namespace)
            phase = pod_status.status.phase
            if phase == "Running":
                break
            elif phase == "Failed" or phase == "Unknown":
                logger.error(f"Pod {pod_name} failed to start. Current phase: {phase}")
                return False
            else:
                time.sleep(1)

        if phase != "Running":
            logger.error(f"timeout waiting for pod {pod_name} to start")
            return False

        try:
            logs = core_v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                follow=True,
                pretty=False,
                _preload_content=False
            )

            for chunk in logs.stream(1024):
                if chunk:
                    enqueue_buildlog_nowait(loop, build_id, chunk.decode())

        except Exception as e:
            logger.error(f"Error streaming logs: {e}")

    def delete_job(self, job_name, namespace):
        batch_v1 = client.BatchV1Api()
        try:
            delete_options = client.V1DeleteOptions(propagation_policy="Foreground")
            batch_v1.delete_namespaced_job(
                    name=job_name,
                    namespace=namespace,
                    body=delete_options
                    )
        except ApiException as e:
            logger.info(f"Exception when deleting Job: {e}")

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
                distrelease = task['distrelease']
                await enqueue_backend({"started": build_id})

                await write_log_title(build_id, "Kubernetes Build")

                server_url = Configuration().server.get("url")
                cfg = Configuration("/etc/molior/backend-kubernetes.yml")
                if not cfg:
                    logger.error("kubernetes-backend: config file not found: /etc/molior/backend-kubernetes.yml")
                    continue

                registry = cfg.registry.get("server")

                namespace = "default"
                jobversion = task['version'].replace("~", "-")
                job_name = f"build-{task['build_id']}-{task['repository_name']}-{jobversion}-" \
                           f"{distrelease}-{distversion}-{arch}"
                job_name = job_name.replace(".", "-")
                image = f"{registry}/molior/{distrelease}-{arch}:{distversion}"

                envvars = [
                        ("BUILD_ID", task['build_id']),
                        ("BUILD_TOKEN", task['token']),
                        ("PLATFORM", task['distrelease']),
                        ("PLATFORM_VERSION", distversion),
                        ("ARCH", arch),
                        ("ARCH_ANY_ONLY", task['arch_any_only']),
                        ("REPO_NAME", task['repository_name']),
                        ("VERSION", task['version']),
                        ("PROJECT_DIST", task['project_dist']),
                        ("PROJECT", task['project']),
                        ("PROJECTVERSION", task['projectversion']),
                        ("APT_SERVER", task['apt_server']),
                        ("APT_KEYS", ' '.join(task['apt_keys'])),
                        ("RUN_LINTIAN", task['run_lintian']),
                        ("MOLIOR_SERVER", server_url),
                        ("APT_SOURCES_INTERNAL", "1"),
                ]

                executor = concurrent.futures.ThreadPoolExecutor()
                loop = asyncio.get_event_loop()
                ret = await loop.run_in_executor(executor, lambda:
                                                 self.create_kubernetes_job(namespace, job_name, image, envvars))
                if not ret:
                    await enqueue_backend({"failed": build_id})
                else:
                    future = loop.run_in_executor(executor, lambda: self.stream_pod_logs(loop, build_id, job_name, namespace))

                    ret = await loop.run_in_executor(executor, lambda: self.monitor_job_status(job_name, namespace))
                    if ret is True:
                        await enqueue_backend({"succeeded": build_id})
                    else:
                        await enqueue_backend({"failed": build_id})

                    await future

                await buildlog(build_id, None)  # signal end of logs

                ret = await loop.run_in_executor(executor, lambda: self.delete_job(job_name, namespace))

            except Exception as exc:
                logger.exception(exc)

            await asyncio.sleep(1)

        logger.info("scheduler %s task terminated", queue_arch)
