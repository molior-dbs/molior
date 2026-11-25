# System tests

`tests/system/system-tests.sh` creates a throwaway k3d cluster with its own registry, deploys molior with the
Helm chart (`charts/`, values `tests/system/values.yaml`), runs pytest from a test runner pod inside the cluster
against `http://web:8000`, collects the results, and removes the cluster, the registry and their volumes.
The current kubectl context and `~/.kube/config` are not touched. The same script is meant for CI.

```
make system-tests                       # all suites (smoke and valid-1.4), as in CI
make system-tests TEST=valid-1.4/validation_tests.py::test_build_order
tests/system/system-tests.sh            # smoke tests
tests/system/system-tests.sh smoke/test_api.py -k token
KEEP=1 tests/system/system-tests.sh     # keep the cluster for debugging, remove it with CLEANUP_ONLY=test-<pid>
```

Needs docker, k3d, helm, kubectl, python3 and the image `molior-base:dev` (`make system-tests` builds it when it is
missing, or `make docker-images`).
Results (junit xml, screenshots of failed UI tests, server logs, server coverage) go to `RESULTS_DIR`
(default `./system-test-results`).

| File | What |
|---|---|
| `system-tests.sh` | cluster, images, install, test run, results, cleanup |
| `values.yaml` | Helm values for the test install |
| `test.Dockerfile` | molior image for the tests: the molior deb from the working copy, test and coverage tools, server coverage |
| `test-web.Dockerfile` | test runner image: pytest, requests, selenium with headless chromium |
| `ctzpos-cups.tar.xz` | repository for `test_mirror` of valid-1.4 (one package, signed), served by the test runner pod (git lfs) |
| `conftest.py` | fixtures: API client (`public`, `admin`), unique names, screenshots on failure |
| `smoke/` | smoke tests: API and web UI, no mirror and no build |
