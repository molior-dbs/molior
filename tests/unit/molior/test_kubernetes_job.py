"""create_kubernetes_job: a build Job is not retried and is removed by Kubernetes after one hour."""
import importlib.util
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


class Spec:
    """Keeps the arguments of a kubernetes client model."""
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


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
        "kubernetes.client.rest": MagicMock(),
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
        yield module.KubernetesBackend.__new__(module.KubernetesBackend), client
        sys.modules.pop("molior.backends.kubernetes.kubernetes", None)


def test_job_has_no_retries_and_a_ttl(backend):
    kube, client = backend
    assert kube.create_kubernetes_job("molior", "build-1-x", "image", [("A", 1)], "kubernetes.io/arch=amd64") is True
    job = client.BatchV1Api().create_namespaced_job.call_args.kwargs["body"]
    assert job.spec.backoff_limit == 0
    assert job.spec.ttl_seconds_after_finished == 3600
    assert job.spec.template.spec.restart_policy == "Never"
