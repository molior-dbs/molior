# Deploy tests

`tests/deploy/deploy-tests.sh` creates a throwaway k3d cluster with its own registry, deploys molior with the Helm
chart (`charts/`, values `tests/deploy/values.yaml`) and maps the molior API (NodePort 30080) and the APT repos
(NodePort 30088) to free ports on `127.0.0.1`. pytest runs **on the host**, because molior-deploy (molior-tools)
needs root, loop devices, nbd, docker and virtualbox. Then it collects the results and removes the cluster. The output is the one of the system tests
(`tests/system/pytest_output.py`: start time, number and time of each test; colors only on a terminal).

```
make deploy-tests                                         # all deploy tests, as in CI
make deploy-tests DEPLOY_TEST="test_deploy.py -k 'basemirror or testproject or dir'"
KEEP=1 tests/deploy/deploy-tests.sh                       # keep the cluster, remove it with CLEANUP_ONLY=deploy-<pid>
```

The tests, in this order:

| Test | What |
|---|---|
| `test_deploy_basemirror` | setup: base mirror `trixie/13` (amd64), filtered to what the build and the deployments need |
| `test_deploy_testproject` | setup: project `molior-validation/1` with https://github.com/molior-dbs/testproject.git, waits for its build |
| `test_molior_deploy` | the 1.4 test (id 4643c058): `molior-deploy` for the variants dir, docker, installer, lxd, vbox and image; 1.5: the installer ISO and the vbox OVA boot in VirtualBox (headless, screenshot after `BOOT_WAIT` seconds, default 60) |

Needs on the host: docker, k3d, helm, kubectl, python3 with pytest, pytest-timeout and requests, sudo without
password for `molior-deploy` (`<user> ALL=(root) NOPASSWD: /usr/sbin/molior-deploy`),
molior-tools (`/usr/sbin/molior-deploy`) and the host tools of the variants (genisoimage, xorriso, syslinux-utils,
mtools, dosfstools, kpartx, qemu-utils, virtualbox, the kernel module nbd). `.github/scripts/install-molior-tools.sh`
installs all of them on a CI runner (molior-tools is built from its git tag). Also the image `molior-base:dev`
(`make deploy-tests` builds it when it is missing). The molior image is the one of the system tests
(`tests/system/test.Dockerfile`, with server coverage).

Results (junit xml, server logs, server coverage) go to `RESULTS_DIR` (default `./deploy-test-results`), the
deployments and the log of each `molior-deploy` call (`-L`) to `RESULTS_DIR/molior-deploy-output/` (several GB). CI
uploads the logs and the screenshots of the VMs with the other results (artifact `tests-deploy`), not the deployments.
