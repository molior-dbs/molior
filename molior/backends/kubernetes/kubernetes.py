import asyncio
import codecs
import concurrent.futures
import re
import time

from collections import namedtuple
from contextlib import suppress
from kubernetes import client, config
from kubernetes.client.rest import ApiException

from ...logger import logger
from ...molior.configuration import Configuration
from ...molior.queues import enqueue_buildtask, dequeue_buildtask, buildlog, enqueue_backend, enqueue_buildlog_nowait
from ...tools import write_log_title


def build_job_name(build_id, repository_name, version, distrelease, distversion, arch):
    """
    Name of the Kubernetes Job of a build. Debian versions may have characters that a Job name must not have
    (CI versions "1.0+git20200101.abc", epochs "1:2.0", "~"): every character but a-z, 0-9 and "-" becomes "-".
    The name is also a label value: max 63 bytes, starting and ending with a letter or digit
    (the build id at the front keeps it unique).
    """
    name = f"build-{build_id}-{repository_name}-{version}-{distrelease}-{distversion}-{arch}"
    name = re.sub(r"[^a-z0-9-]", "-", name.lower())
    return name[:63].rstrip("-")


NAMESPACE_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"

# container waiting reasons which do not go away by waiting
FATAL_WAITING = {"InvalidImageName", "ErrImageNeverPull", "CreateContainerConfigError", "CreateContainerError"}
# pull errors: final if the image does not exist, otherwise (registry not reachable, ...) Kubernetes retries
PULL_WAITING = {"ErrImagePull", "ImagePullBackOff"}
IMAGE_NOT_FOUND = re.compile(r"not found|manifest unknown|does not exist", re.IGNORECASE)

PodState = namedtuple("PodState", ["state", "reason", "message", "started"])


def get_namespace():
    """The namespace of the molior pod (of its service account), "molior" outside of a cluster."""
    try:
        with open(NAMESPACE_FILE, encoding="utf-8") as f:
            return f.read().strip() or "molior"
    except OSError:
        return "molior"


def node_usable(node):
    """True if build pods can be scheduled on the node: Ready, not cordoned, no NoSchedule or NoExecute taint."""
    if node.spec.unschedulable:
        return False
    if any(t.effect in ("NoSchedule", "NoExecute") for t in (node.spec.taints or [])):
        return False
    return any(c.type == "Ready" and c.status == "True" for c in (node.status.conditions or []))


def pod_state(pod):
    """
    State of a build pod: PodState(state, reason, message, started).
    state: pending (waiting for a node, an image pull, ...), running, succeeded or failed.
    started: a container of the pod is running or has run (its log can be read).
    A pod waiting for a node is pending (congestion is normal), a missing image or a broken pod spec is failed.
    """
    status = pod.status
    containers = status.container_statuses or []
    started = any(c.state.running or c.state.terminated for c in containers)

    if status.phase == "Succeeded":
        return PodState("succeeded", "", "", True)

    pending = None
    for c in (status.init_container_statuses or []) + containers:
        if c.state.terminated and c.state.terminated.exit_code != 0:
            t = c.state.terminated
            message = f"exit code {t.exit_code}" + (f": {t.message}" if t.message else "")
            return PodState("failed", t.reason or "Error", message, started)
        waiting = c.state.waiting
        if not waiting:
            continue
        message = waiting.message or ""
        if waiting.reason in FATAL_WAITING:
            return PodState("failed", waiting.reason, message, started)
        if waiting.reason in PULL_WAITING:
            if IMAGE_NOT_FOUND.search(message):
                return PodState("failed", waiting.reason, message, started)
            pending = pending or PodState("pending", waiting.reason, message, started)

    if status.phase == "Failed":
        return PodState("failed", status.reason or "Failed", status.message or "", started)
    if pending:
        return pending
    if started:
        return PodState("running", "", "", True)
    for cond in status.conditions or []:
        if cond.type == "PodScheduled" and cond.status == "False":
            return PodState("pending", cond.reason or "", cond.message or "", False)
    return PodState("pending", "", "", False)


def job_state(job):
    """("failed", message), ("succeeded", "") or (None, "") from the conditions of a Job."""
    for cond in (job.status.conditions or []) if job.status else []:
        if cond.status != "True":
            continue
        if cond.type == "Failed":
            return "failed", f"Job failed: {cond.reason}: {cond.message}"
        if cond.type == "Complete":
            return "succeeded", ""
    return None, ""


class KubernetesBackend:
    poll_interval = 2          # seconds between two checks of a build Job
    api_error_timeout = 300    # a build fails after the Kubernetes API failed this long without a break
    log_timeout = 60           # seconds to wait for the end of the log stream after the build pod ended

    def __init__(self, _):
        self.builds = {}       # build_id: Job name (None while the build is queued) of the builds of this backend
        self.aborted = set()   # build_ids to abort
        self.deleting = set()  # build_ids whose Job molior deletes (the end of their log stream is expected)
        self.node_check = True
        self.namespace = get_namespace()

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
        self.builds[build_id] = None
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
        """
        Aborts a queued or running build: a queued build is not started, the Job of a running (or pending) build is
        deleted within one poll interval; the build fails.
        """
        if build_id not in self.builds:
            logger.info(f"kubernetes backend: build {build_id} to abort is not queued or running")
            return
        logger.info(f"kubernetes backend: aborting build {build_id}")
        self.aborted.add(build_id)

    def get_nodes_info(self):
        return []

    async def stop(self):
        logger.info("stopping kubernetes backend")
        for arch in ["amd64", "arm64"]:
            for sched in self.scheduler[arch]:
                sched.cancel()
                with suppress(asyncio.CancelledError):
                    await sched

    def create_kubernetes_job(self, namespace, job_name, image, envvars, node_label):
        container = client.V1Container(
            name=job_name,
            image=image,
            env=[client.V1EnvVar(name=en, value=str(ev)) for en, ev in envvars],
            args=["/app/docker-build"]
        )

        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels={"job-name": job_name}),
            spec=client.V1PodSpec(restart_policy="Never", containers=[container],
                                  node_selector=dict([node_label.split("=", 1)]))
        )

        # no retries: molior treats the first failed pod as a failed build (a Job left behind by a molior restart
        # would otherwise build up to 6 times); finished Jobs and their pods are removed by Kubernetes after 1 hour
        job_spec = client.V1JobSpec(template=template, backoff_limit=0, ttl_seconds_after_finished=3600)

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

    def count_nodes(self, node_label):
        """
        (all, usable): the nodes with the label and the ones build pods can be scheduled on.
        None if molior may not list nodes (no ClusterRole): then the check is skipped.
        """
        if not self.node_check:
            return None
        try:
            nodes = client.CoreV1Api().list_node(label_selector=node_label).items
        except ApiException as exc:
            if exc.status == 403:
                logger.warning("kubernetes backend: not allowed to list nodes, the build node check is skipped")
                self.node_check = False
                return None
            raise
        return len(nodes), len([n for n in nodes if node_usable(n)])

    def read_job(self, job_name, namespace):
        """The Job, None if it does not exist (any more)."""
        try:
            return client.BatchV1Api().read_namespaced_job(name=job_name, namespace=namespace)
        except ApiException as exc:
            if exc.status == 404:
                return None
            raise

    def list_pods(self, job_name, namespace):
        return client.CoreV1Api().list_namespaced_pod(namespace=namespace, label_selector=f"job-name={job_name}").items

    def pod_event_messages(self, pod_name, namespace):
        """Messages of the Failed events of a pod (they have the image pull error), [] if they cannot be read."""
        try:
            events = client.CoreV1Api().list_namespaced_event(namespace=namespace,
                                                              field_selector=f"involvedObject.name={pod_name}")
        except Exception as exc:
            logger.warning(f"kubernetes backend: cannot read the events of pod {pod_name}: {exc}")
            return []
        return [e.message for e in events.items if e.reason == "Failed" and e.message]

    async def wait_for_job(self, build_id, job_name, namespace, node_label, call, on_started):
        """
        Follows the Job of a build until it ends: returns (ok, message), message is the reason of a failure.
        call(fn, *args): runs a blocking Kubernetes call (in a thread) and returns its result.
        on_started(pod_name): called once when the build pod runs (or ran).
        Waiting for a node has no timeout: the reason is written to the build log when it changes. The build fails
        if no node has the node label, if the image does not exist, the pod spec is broken, the pod or the Job
        failed, the Job was deleted, the build was aborted, or the Kubernetes API failed for api_error_timeout.
        """
        started = False
        last_info = None
        api_error_since = None
        while True:
            if build_id in self.aborted:
                return False, "build aborted"
            try:
                job = await call(self.read_job, job_name, namespace)
                pods = await call(self.list_pods, job_name, namespace) if job else []
                api_error_since = None
            except Exception as exc:
                now = time.monotonic()
                api_error_since = api_error_since or now
                if now - api_error_since >= self.api_error_timeout:
                    return False, f"Kubernetes API failed for {int(now - api_error_since)}s: {exc}"
                logger.warning(f"kubernetes backend: build {build_id}: Kubernetes API error: {exc}")
                await asyncio.sleep(self.poll_interval)
                continue

            if job is None:
                return False, "the Job was deleted"

            info = None
            if pods:
                pod = pods[0]
                state = pod_state(pod)
                if state.state == "pending" and state.reason in PULL_WAITING:
                    messages = await call(self.pod_event_messages, pod.metadata.name, namespace)
                    missing = [m for m in messages if IMAGE_NOT_FOUND.search(m)]
                    if missing:
                        state = PodState("failed", state.reason, missing[-1], state.started)
                if state.started and not started:
                    started = True
                    await on_started(pod.metadata.name)
                if state.state == "succeeded":
                    return True, ""
                if state.state == "failed":
                    return False, f"build pod: {state.reason}: {state.message}"
                if state.state == "pending":
                    if state.reason == "Unschedulable":
                        info = f"waiting for a node with label {node_label}: {state.message}"
                    elif state.reason:
                        info = f"waiting for the build pod: {state.reason}: {state.message}"
                    if state.reason == "Unschedulable" and info != last_info:
                        nodes = await call(self.count_nodes, node_label)
                        if nodes is not None and nodes[0] == 0:
                            return False, f"no node with label {node_label} in the cluster"
            else:
                info = "waiting for the build pod"

            jstate, jmessage = job_state(job)
            if jstate == "failed":
                return False, jmessage
            if jstate == "succeeded":
                return True, ""

            if info and info != last_info:
                await buildlog(build_id, f"I: {info}\n")
                last_info = info
            await asyncio.sleep(self.poll_interval)

    def stream_pod_logs(self, loop, build_id, pod_name, namespace):
        """Copies the log of the build pod to the build log until the pod ends (runs in a thread)."""
        def send(text):
            loop.call_soon_threadsafe(enqueue_buildlog_nowait, loop, build_id, text)

        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            logs = client.CoreV1Api().read_namespaced_pod_log(name=pod_name, namespace=namespace, follow=True,
                                                              pretty=False, _preload_content=False)
            for chunk in logs.stream(1024):
                if chunk:
                    send(decoder.decode(chunk))
            send(decoder.decode(b"", final=True))
        except Exception as exc:
            if build_id in self.deleting:
                return
            logger.error(f"kubernetes backend: build {build_id}: error streaming the log of pod {pod_name}: {exc}")
            send(f"\nW: the log of the build pod was interrupted: {exc}\n")

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
            if e.status != 404:
                logger.info(f"Exception when deleting Job: {e}")

    async def run_build(self, queue_arch, task, call, ctx):
        """Runs one build task. Returns (ok, message); the Job name and the log stream are kept in ctx."""
        build_id = task["build_id"]
        if build_id in self.aborted:
            return False, "build aborted"

        await write_log_title(build_id, "Kubernetes Build")

        server_url = Configuration().server.get("url")
        cfg = Configuration("/etc/molior/backend-kubernetes.yml")
        if not cfg:
            return False, "config file not found: /etc/molior/backend-kubernetes.yml"

        registry = cfg.registry.get("server")
        # the one node label build pods of this queue need (key=value), default: the architecture label
        node_label = (cfg.builder.get(queue_arch) or {}).get("nodeLabel") or f"kubernetes.io/arch={queue_arch}"

        nodes = await call(self.count_nodes, node_label)
        if nodes is not None:
            total, usable = nodes
            if total == 0:
                return False, f"no node with label {node_label} in the cluster"
            if usable == 0:
                await buildlog(build_id, f"I: {total} node(s) with label {node_label}, none ready, waiting\n")

        if build_id in self.aborted:  # aborted during the node check
            return False, "build aborted"

        arch = task['architecture']
        distversion = task['distversion']
        distrelease = task['distrelease']
        namespace = self.namespace
        job_name = build_job_name(build_id, task['repository_name'], task['version'], distrelease, distversion, arch)
        image = f"{registry}/molior/{distrelease}-{arch}:{distversion}"

        envvars = [
                ("BUILD_ID", build_id),
                ("BUILD_TOKEN", task['token']),
                ("PLATFORM", distrelease),
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

        if not await call(self.create_kubernetes_job, namespace, job_name, image, envvars, node_label):
            return False, f"could not create the Job {job_name}"
        ctx["job_name"] = job_name
        self.builds[build_id] = job_name

        loop = asyncio.get_running_loop()

        async def on_started(pod_name):
            await enqueue_backend({"started": build_id})
            ctx["log"] = call(self.stream_pod_logs, loop, build_id, pod_name, namespace)

        return await self.wait_for_job(build_id, job_name, namespace, node_label, call, on_started)

    async def finish_build(self, build_id, ok, message, call, ctx):
        """
        Ends the build log, reports the result and deletes the Job.
        A failed or aborted build: the Job is deleted first, this stops a running pod and ends its log stream
        (an aborted running build would otherwise build on until the log timeout).
        A successful build: the rest of the log is read first, then the Job is deleted.
        """
        job_name = ctx.get("job_name")
        if job_name and not ok:
            self.deleting.add(build_id)
            await call(self.delete_job, job_name, self.namespace)
        if ctx.get("log"):
            await asyncio.wait({ctx["log"]}, timeout=self.log_timeout)
        if not ok and message:
            await buildlog(build_id, f"\nE: {message}\n")
        await enqueue_backend({"succeeded" if ok else "failed": build_id})
        await buildlog(build_id, None)  # signal end of logs
        if job_name and ok:
            await call(self.delete_job, job_name, self.namespace)

    async def consumer(self, queue_arch):
        while True:
            task = await dequeue_buildtask(queue_arch)
            if task is None:
                break
            build_id = task["build_id"]
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
            loop = asyncio.get_running_loop()

            def call(fn, *args):
                return loop.run_in_executor(executor, fn, *args)

            ctx = {}
            try:
                try:
                    ok, message = await self.run_build(queue_arch, task, call, ctx)
                except asyncio.CancelledError:
                    raise  # molior stops: a running Job is left, the build is continued at the next start
                except Exception as exc:
                    logger.exception(exc)
                    ok, message = False, f"internal error: {exc}"
                await self.finish_build(build_id, ok, message, call, ctx)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(exc)
            finally:
                executor.shutdown(wait=False)
                self.builds.pop(build_id, None)
                self.aborted.discard(build_id)
                self.deleting.discard(build_id)

        logger.info("scheduler %s task terminated", queue_arch)
