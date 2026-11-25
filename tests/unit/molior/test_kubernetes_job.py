"""create_kubernetes_job: a build Job is not retried and is removed by Kubernetes after one hour.
build_job_name: a valid Job name for every Debian version.
pod_state, node_usable, wait_for_job, abort, run_build: how a build Job is followed (states of pods, Jobs and nodes)."""
import asyncio
import importlib.util
import re
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


class Spec:
    """Keeps the arguments of a kubernetes client model."""
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeApiException(Exception):
    def __init__(self, status):
        super().__init__(f"status {status}")
        self.status = status


@pytest.fixture
def backend():
    client = MagicMock()
    for name in ["V1Container", "V1EnvVar", "V1PodTemplateSpec", "V1ObjectMeta", "V1PodSpec", "V1JobSpec", "V1Job"]:
        setattr(client, name, Spec)
    package = types.ModuleType("molior.backends.kubernetes")
    package.__path__ = ["molior/backends/kubernetes"]
    stubs = {
        "kubernetes": MagicMock(client=client),
        "kubernetes.client": client,
        "kubernetes.client.rest": MagicMock(ApiException=FakeApiException),
        "molior.backends": types.ModuleType("molior.backends"),
        "molior.backends.kubernetes": package,
        "molior.logger": MagicMock(),
        "molior.molior": MagicMock(),
        "molior.molior.configuration": MagicMock(),
        "molior.molior.queues": MagicMock(),
        "molior.tools": MagicMock(),
    }
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location(
            "molior.backends.kubernetes.kubernetes", "molior/backends/kubernetes/kubernetes.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["molior.backends.kubernetes.kubernetes"] = module
        spec.loader.exec_module(module)
        backend = module.KubernetesBackend.__new__(module.KubernetesBackend)
        backend.module = module
        backend.builds = {}
        backend.aborted = set()
        backend.deleting = set()
        backend.node_check = True
        backend.namespace = "molior"
        backend.poll_interval = 0
        yield backend, client
        sys.modules.pop("molior.backends.kubernetes.kubernetes", None)


def test_job_has_no_retries_and_a_ttl(backend):
    kube, client = backend
    assert kube.create_kubernetes_job("molior", "build-1-x", "image", [("A", 1)], "kubernetes.io/arch=amd64") is True
    job = client.BatchV1Api().create_namespaced_job.call_args.kwargs["body"]
    assert job.spec.backoff_limit == 0
    assert job.spec.ttl_seconds_after_finished == 3600
    assert job.spec.template.spec.restart_policy == "Never"


@pytest.mark.parametrize("version, expected", [
    ("1.0.2", "build-100-mypkg-1-0-2-trixie-13-amd64"),
    ("0.0.1+git20200101120000.abc123", "build-100-mypkg-0-0-1-git20200101120000-abc123-trixie-13-amd64"),
    ("1:2.0~rc1", "build-100-mypkg-1-2-0-rc1-trixie-13-amd64"),
])
def test_job_name_is_valid(backend, version, expected):
    kube, _ = backend
    assert kube.module.build_job_name(100, "mypkg", version, "trixie", "13", "amd64") == expected


def test_job_name_is_cut_to_a_valid_label(backend):
    kube, _ = backend
    name = kube.module.build_job_name(100, "My_Package", "0.0.1+git20200101120000.abcdef1234567890", "trixie", "13",
                                      "amd64")
    assert len(name) <= 63
    assert re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?", name), name
    assert name.startswith("build-100-my-package-")


def ns(**kwargs):
    return types.SimpleNamespace(**kwargs)


def container(running=False, waiting=None, terminated=None):
    return ns(state=ns(running=ns() if running else None, waiting=waiting, terminated=terminated))


def waiting(reason, message=""):
    return ns(reason=reason, message=message)


def terminated(exit_code, reason="Error", message=None):
    return ns(exit_code=exit_code, reason=reason, message=message)


def pod(phase="Pending", containers=None, init=None, conditions=None, reason=None, message=None, name="pod-1"):
    return ns(metadata=ns(name=name),
              status=ns(phase=phase, container_statuses=containers, init_container_statuses=init,
                        conditions=conditions, reason=reason, message=message))


UNSCHEDULABLE = [ns(type="PodScheduled", status="False", reason="Unschedulable",
                    message="0/1 nodes are available: 1 node(s) didn't match Pod's node affinity/selector.")]


def job(conditions=None):
    return ns(status=ns(conditions=conditions))


def node(ready=True, unschedulable=False, taints=None):
    return ns(spec=ns(unschedulable=unschedulable, taints=taints),
              status=ns(conditions=[ns(type="Ready", status="True" if ready else "False")]))


# pod_state

def test_pod_waiting_for_a_node_is_pending(backend):
    kube, _ = backend
    state = kube.module.pod_state(pod(conditions=UNSCHEDULABLE))
    assert (state.state, state.reason, state.started) == ("pending", "Unschedulable", False)
    assert "node affinity/selector" in state.message


@pytest.mark.parametrize("message", [
    'rpc error: code = NotFound desc = failed to pull and unpack image "registry/molior/trixie-arm64:13": not found',
    "manifest unknown: manifest unknown",
    "pull access denied, repository does not exist or may require authorization",
])
def test_pod_with_a_missing_image_failed(backend, message):
    kube, _ = backend
    state = kube.module.pod_state(pod(containers=[container(waiting=waiting("ErrImagePull", message))]))
    assert (state.state, state.reason) == ("failed", "ErrImagePull")


@pytest.mark.parametrize("reason, message", [
    ("ErrImagePull", "dial tcp 10.0.0.1:5000: connect: connection refused"),
    ("ImagePullBackOff", 'Back-off pulling image "registry/molior/trixie-amd64:13"'),
])
def test_pod_with_a_temporary_pull_error_is_pending(backend, reason, message):
    kube, _ = backend
    state = kube.module.pod_state(pod(containers=[container(waiting=waiting(reason, message))]))
    assert (state.state, state.reason) == ("pending", reason)


@pytest.mark.parametrize("reason", ["CreateContainerConfigError", "InvalidImageName", "CreateContainerError"])
def test_pod_with_a_broken_spec_failed(backend, reason):
    kube, _ = backend
    assert kube.module.pod_state(pod(containers=[container(waiting=waiting(reason, "x"))])).state == "failed"


def test_failed_init_container_fails_the_pod(backend):
    kube, _ = backend
    state = kube.module.pod_state(pod(init=[container(terminated=terminated(1))],
                                      containers=[container(waiting=waiting("PodInitializing"))]))
    assert (state.state, state.message) == ("failed", "exit code 1")


def test_pod_states_of_a_build(backend):
    kube, _ = backend
    assert kube.module.pod_state(pod("Running", [container(running=True)])) == ("running", "", "", True)
    assert kube.module.pod_state(pod("Succeeded", [container(terminated=terminated(0, "Completed"))])).state == \
        "succeeded"
    state = kube.module.pod_state(pod("Failed", [container(terminated=terminated(2, "Error"))]))
    assert (state.state, state.reason, state.message, state.started) == ("failed", "Error", "exit code 2", True)
    state = kube.module.pod_state(pod("Failed", [container(terminated=terminated(137, "OOMKilled"))]))
    assert (state.state, state.reason) == ("failed", "OOMKilled")
    state = kube.module.pod_state(pod("Failed", [], reason="Evicted", message="low on memory"))
    assert (state.state, state.reason, state.message) == ("failed", "Evicted", "low on memory")


def test_node_usable(backend):
    kube, _ = backend
    assert kube.module.node_usable(node())
    assert not kube.module.node_usable(node(ready=False))
    assert not kube.module.node_usable(node(unschedulable=True))
    assert not kube.module.node_usable(node(taints=[ns(effect="NoSchedule")]))
    assert kube.module.node_usable(node(taints=[ns(effect="PreferNoSchedule")]))


def test_job_state(backend):
    kube, _ = backend
    assert kube.module.job_state(job()) == (None, "")
    assert kube.module.job_state(job([ns(type="Complete", status="True")])) == ("succeeded", "")
    state, message = kube.module.job_state(job([ns(type="Failed", status="True", reason="DeadlineExceeded",
                                                   message="too long")]))
    assert state == "failed" and "DeadlineExceeded" in message


# wait_for_job

class Cluster:
    """Answers of the Kubernetes calls of wait_for_job, one per poll (the last one is repeated)."""
    def __init__(self, kube, pods, jobs=None, nodes=(1, 1), events=()):
        self.pods, self.jobs, self.nodes, self.events = list(pods), list(jobs or [job()]), nodes, list(events)
        self.calls = []
        kube.read_job = self.read_job
        kube.list_pods = self.list_pods
        kube.count_nodes = lambda label: self.nodes
        kube.pod_event_messages = lambda name, namespace: self.events

    def next(self, answers):
        return answers.pop(0) if len(answers) > 1 else answers[0]

    def read_job(self, name, namespace):
        self.calls.append("job")
        answer = self.next(self.jobs)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def list_pods(self, name, namespace):
        answer = self.next(self.pods)
        return answer() if callable(answer) else answer


def wait(kube, logs, started=None):
    async def call(fn, *args):
        return fn(*args)

    async def on_started(name):
        if started is not None:
            started.append(name)

    async def buildlog(build_id, msg):
        logs.append(msg)

    kube.module.buildlog = buildlog
    return asyncio.run(kube.wait_for_job(100, "build-100", "molior", "kubernetes.io/arch=arm64", call, on_started))


def test_build_waits_for_a_busy_node_and_succeeds(backend):
    kube, _ = backend
    kube.builds[100] = "build-100"
    busy = [ns(type="PodScheduled", status="False", reason="Unschedulable", message="0/3 nodes: 3 Insufficient cpu.")]
    Cluster(kube, [[pod(conditions=busy)]] * 5 + [[pod("Running", [container(running=True)])]] +
            [[pod("Succeeded", [container(terminated=terminated(0, "Completed"))])]], nodes=(3, 3))
    logs, started = [], []
    assert wait(kube, logs, started) == (True, "")
    assert started == ["pod-1"]
    # the reason is written once, not at every poll
    assert logs == ["I: waiting for a node with label kubernetes.io/arch=arm64: 0/3 nodes: 3 Insufficient cpu.\n"]


def test_build_fails_without_a_node_with_the_label(backend):
    kube, _ = backend
    Cluster(kube, [[pod(conditions=UNSCHEDULABLE)]], nodes=(0, 0))
    ok, message = wait(kube, [])
    assert not ok and message == "no node with label kubernetes.io/arch=arm64 in the cluster"


def test_build_waits_when_nodes_cannot_be_listed(backend):
    kube, _ = backend
    kube.builds[100] = "build-100"
    cluster = Cluster(kube, [[pod(conditions=UNSCHEDULABLE)]] * 3 +
                      [lambda: kube.aborted.add(100) or [pod(conditions=UNSCHEDULABLE)]], nodes=None)
    ok, message = wait(kube, [])
    # 4 polls waiting (no node check possible), the abort during the 4th ends the wait before the 5th reads the Job
    assert (ok, message) == (False, "build aborted")
    assert len(cluster.calls) == 4


def test_build_fails_when_the_image_is_missing(backend):
    kube, _ = backend
    Cluster(kube, [[pod(containers=[container(waiting=waiting("ErrImagePull", "failed to pull: not found"))])]])
    ok, message = wait(kube, [])
    assert not ok and message == "build pod: ErrImagePull: failed to pull: not found"


def test_backoff_without_detail_reads_the_events(backend):
    kube, _ = backend
    Cluster(kube, [[pod(containers=[container(waiting=waiting("ImagePullBackOff", "Back-off pulling image"))])]],
            events=['Failed to pull image "x": rpc error: code = NotFound desc = x: not found'])
    ok, message = wait(kube, [])
    assert not ok and "code = NotFound" in message


def test_failed_build_pod_fails_the_build(backend):
    kube, _ = backend
    Cluster(kube, [[pod("Running", [container(running=True)])],
                   [pod("Failed", [container(terminated=terminated(1, "Error"))])]])
    started = []
    ok, message = wait(kube, [], started)
    assert (ok, message, started) == (False, "build pod: Error: exit code 1", ["pod-1"])


def test_deleted_job_fails_the_build(backend):
    kube, _ = backend
    Cluster(kube, [[]], jobs=[job(), None])
    ok, message = wait(kube, [])
    assert (ok, message) == (False, "the Job was deleted")


def test_api_errors_fail_the_build_after_the_timeout(backend):
    kube, _ = backend
    kube.api_error_timeout = 0
    Cluster(kube, [[]], jobs=[FakeApiException(500)])
    ok, message = wait(kube, [])
    assert not ok and message.startswith("Kubernetes API failed")


def test_short_api_errors_are_retried(backend):
    kube, _ = backend
    Cluster(kube, [[pod("Succeeded", [container(terminated=terminated(0, "Completed"))])]],
            jobs=[FakeApiException(500), job()])
    assert wait(kube, []) == (True, "")


# abort

def test_abort_only_marks_builds_of_this_backend(backend):
    kube, _ = backend
    asyncio.run(kube.abort(100))
    assert kube.aborted == set()
    kube.builds[100] = None
    asyncio.run(kube.abort(100))
    assert kube.aborted == {100}


def test_aborted_queued_build_is_not_started(backend):
    kube, _ = backend
    kube.aborted.add(100)
    kube.module.write_log_title = MagicMock(side_effect=AssertionError("must not start"))
    assert asyncio.run(kube.run_build("arm64", {"build_id": 100}, None, {})) == (False, "build aborted")


# run_build

def test_no_node_with_the_label_fails_before_the_job_is_created(backend):
    kube, client = backend

    async def nothing(*args, **kwargs):
        pass

    kube.module.write_log_title = nothing
    kube.module.Configuration = MagicMock(return_value=MagicMock(
        builder={"arm64": {"nodeLabel": "kubernetes.io/arch=arm64"}}))
    kube.count_nodes = lambda label: (0, 0)
    kube.create_kubernetes_job = MagicMock(side_effect=AssertionError("no Job without a node"))

    async def call(fn, *args):
        return fn(*args)

    ctx = {}
    ok, message = asyncio.run(kube.run_build("arm64", {"build_id": 100}, call, ctx))
    assert (ok, message) == (False, "no node with label kubernetes.io/arch=arm64 in the cluster")
    assert ctx == {}


def test_count_nodes_skips_the_check_without_permission(backend):
    kube, client = backend
    client.CoreV1Api().list_node.side_effect = FakeApiException(403)
    assert kube.count_nodes("kubernetes.io/arch=arm64") is None
    assert kube.node_check is False
    client.CoreV1Api().list_node.side_effect = None
    client.CoreV1Api().list_node.return_value = ns(items=[node(), node(ready=False)])
    assert kube.count_nodes("kubernetes.io/arch=arm64") is None
    kube.node_check = True
    assert kube.count_nodes("kubernetes.io/arch=arm64") == (2, 1)


def test_abort_during_the_node_check_creates_no_job(backend):
    kube, _ = backend

    async def nothing(*args, **kwargs):
        pass

    kube.module.write_log_title = nothing
    kube.module.Configuration = MagicMock(return_value=MagicMock(
        builder={"arm64": {"nodeLabel": "kubernetes.io/arch=arm64"}}))
    kube.count_nodes = lambda label: kube.aborted.add(100) or (1, 1)
    kube.create_kubernetes_job = MagicMock(side_effect=AssertionError("no Job after an abort"))
    task = {"build_id": 100, "architecture": "arm64", "distversion": "13", "distrelease": "trixie",
            "repository_name": "pkg", "version": "1.0"}

    async def call(fn, *args):
        return fn(*args)

    assert asyncio.run(kube.run_build("arm64", task, call, {})) == (False, "build aborted")


def finish(kube, ok, message):
    """Runs finish_build with a running log stream which ends when the Job is deleted; returns the order of events
    and the seconds it took."""
    events = []

    async def run():
        deleted = asyncio.Event()

        async def stream():
            await deleted.wait()
            events.append("log ended")

        def delete_job(name, namespace):
            events.append("job deleted")
            deleted.set()

        async def buildlog(build_id, msg):
            events.append(msg if msg is None else msg.strip())

        async def enqueue_backend(msg):
            events.append(msg)

        async def call(fn, *args):
            return fn(*args)

        kube.module.buildlog = buildlog
        kube.module.enqueue_backend = enqueue_backend
        kube.delete_job = delete_job
        ctx = {"job_name": "build-100", "log": asyncio.ensure_future(stream())}
        start = asyncio.get_running_loop().time()
        await kube.finish_build(100, ok, message, call, ctx)
        return asyncio.get_running_loop().time() - start

    kube.log_timeout = 0.5
    return events, asyncio.run(run())


def test_aborted_running_build_deletes_the_job_first(backend):
    kube, _ = backend
    events, seconds = finish(kube, False, "build aborted")
    assert events == ["job deleted", "log ended", "E: build aborted", {"failed": 100}, None]
    assert seconds < 0.4  # no wait for the log timeout
    assert 100 in kube.deleting  # the end of the log stream is expected, no W: line


def test_successful_build_reads_the_log_before_the_job_is_deleted(backend):
    kube, _ = backend
    events, seconds = finish(kube, True, "")
    # the stream of this fake only ends when the Job is gone: finish_build waits the log timeout, then deletes
    assert events == [{"succeeded": 100}, None, "job deleted", "log ended"]
    assert seconds >= 0.5
