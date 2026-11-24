"""create_kubernetes_job: a build Job is not retried and is removed by Kubernetes after one hour.
build_job_name: a valid Job name for every Debian version."""
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
        backend = module.KubernetesBackend.__new__(module.KubernetesBackend)
        backend.module = module
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
