# Deploy tests

`tests/deploy/deploy-tests.sh` creates a throwaway k3d cluster with its own registry, deploys molior with the Helm
chart (`charts/`, values `tests/deploy/values.yaml`) and maps the molior API (NodePort 30080) and the APT repos
(NodePort 30088) to free ports on `127.0.0.1`. pytest runs **on the host**, because molior-deploy (molior-tools)
needs root, loop devices, nbd, docker and virtualbox. Then it collects the results and removes the cluster. The output is the one of the system tests
(`tests/system/pytest_output.py`: start time, number and time of each test, the eta of the run from `RUN_MINUTES`
in `conftest.py` (20); colors only on a terminal).

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
| `test_molior_deploy` | the 1.4 test (id 4643c058): `molior-deploy` for the variants dir, docker, lxd, image, vbox and installer (fast content checks first, the VM boots last; 1.4: dir, docker, installer, lxd, vbox, image); 1.5: a few top level packages are installed in the dir, docker, lxd and image deployments (`deployment_packages`, read from their dpkg status file without root), the installer ISO and the vbox OVA boot in VirtualBox (headless, screenshots; the installer installs onto the VM disk and the installed system boots, see below) |

Needs on the host: docker, k3d, helm, kubectl, python3 with pytest, pytest-timeout and requests, sudo without
password for `molior-deploy` (`<user> ALL=(root) NOPASSWD: /usr/sbin/molior-deploy`),
molior-tools (`/usr/sbin/molior-deploy`) and the host tools of the variants (genisoimage, xorriso, syslinux-utils,
mtools, dosfstools, kpartx, qemu-utils, virtualbox, the kernel module nbd; for the package check of image e2fsprogs
and fdisk). `.github/scripts/install-molior-tools.sh`
installs all of them on a CI runner (molior-tools is built from its git tag). Also the image `molior-base:dev`
(`make deploy-tests` builds it when it is missing). The molior image is the one of the system tests
(`tests/system/test.Dockerfile`, with server coverage).

Results (junit xml, server logs, server coverage) go to `RESULTS_DIR` (default `./deploy-test-results`), the
deployments and the log of each `molior-deploy` call (`-L`) to `RESULTS_DIR/molior-deploy-output/` (several GB). CI
uploads the logs and the screenshots of the VMs with the other results (artifact `tests-deploy`), not the deployments.
The deployments are found by their type (`*_installer.iso`, `*_vbox.ova`, ...), not by the version in their name.
The deployment of a failed `test_molior_deploy` is copied to `RESULTS_DIR/failed-deployments/` (`conftest.py`), also
when `test-deploy.sh` failed after molior-deploy; CI uploads it as the artifact `failed-deployments` (3 days) to
download and debug it. The installer ISO is uploaded in every run (artifact `installer-iso`, 3 days).

The VM deployments boot in VirtualBox (headless, `utils.boot_vm`), the screenshots go to `molior-deploy-output/`:

| Deployment | Screenshots |
|---|---|
| vbox (OVA) | `<deployment>.png` after `BOOT_WAIT` seconds (default 60): the LXDE desktop (autologin of the user `molior`) |
| installer (ISO, VM with an empty 8 GB disk) | `<deployment>.png` after `BOOT_WAIT` seconds: the hostname question; then Enter (default hostname) and Enter (confirm); `<deployment>.done.png` when the installer is done (it ejected the ISO); Enter (reboot); `<deployment>.installed.png` of the installed system after `BOOT_WAIT` seconds. ISO not ejected after `INSTALL_WAIT` seconds (default 300, a failed installer does not eject it): fails with `<deployment>.failed.png` |
