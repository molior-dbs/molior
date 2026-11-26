"""Helpers of the deploy tests: the API calls that create the base mirror and the project, and the waits.
The tests run on the runner host (molior-deploy needs root, loop devices and docker), so the URLs are the ports
that tests/deploy/deploy-tests.sh maps from the test cluster to the host."""
import gzip
import json
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
import time

import requests

MOLIOR_URL = os.environ.get("MOLIOR_URL", "http://127.0.0.1:30080").rstrip("/")
APTLY_URL = os.environ.get("APTLY_URL", "http://127.0.0.1:30088").rstrip("/")
ADMIN_PASSWORD = os.environ.get("MOLIOR_ADMIN_PASSWORD", "")
RESULTS = os.environ.get("RESULTS_DIR", "/tmp/results")
MIRROR_TIMEOUT = int(os.environ.get("MIRROR_TIMEOUT", "3600"))
BUILD_TIMEOUT = int(os.environ.get("BUILD_TIMEOUT", "1800"))
# version of the testproject packages in the deployment file names (as fixed in test-deploy.sh)
TESTPROJECT_VERSION = "3.0.13"
# seconds a VM of a deployment runs before the screenshot (boot_vm)
BOOT_WAIT = int(os.environ.get("BOOT_WAIT", "60"))
# installer: how long the installation may take, and how long the disk does not grow when the installer is done
INSTALL_WAIT = int(os.environ.get("INSTALL_WAIT", "1200"))
INSTALL_IDLE = int(os.environ.get("INSTALL_IDLE", "120"))
# where test-deploy.sh runs molior-deploy: the deployments, their logs and screenshots (CI uploads the logs and
# the screenshots, artifact "tests-deploy")
DEPLOY_OUTPUT = os.path.join(RESULTS, "molior-deploy-output")
# build states that do not change any more (molior/model/build.py BUILD_STATES)
FINAL_STATES = ("successful", "build_failed", "publish_failed", "already_exists", "already_failed", "nothing_done")

logger = logging.getLogger("molior-deploy-tests")


def molior_session():
    session = requests.Session()
    r = session.post(MOLIOR_URL + "/api/login", json={"username": "admin", "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    return session


def save(name, data):
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, name), "w") as f:
        json.dump(data, f, indent=2)


def create_basemirror(name, version, url, dist, components, architectures, keyserver, keys, mirror_filter):
    """Creates a base mirror (filtered, with the dependencies of the filter) and waits until it and its build
    environments are done. Fails if one of them failed."""
    session = molior_session()
    payload = {
        "mirrorname": name,
        "mirrorversion": version,
        "mirrortype": "1",
        "mirrorurl": url,
        "mirrordist": dist,
        "mirrorcomponents": components,
        "architectures": architectures,
        "mirrorfilter": mirror_filter,
        "mirrorfilterwithdeps": True,
        "mirrorkeyserver": keyserver,
        "mirrorkeyids": keys,
    }
    start = time.time()
    res = session.post(MOLIOR_URL + "/api2/mirror", json=payload, timeout=60)
    assert res.status_code == 200, "mirror {}/{}: {} {}".format(name, version, res.status_code, res.text)
    build_id = res.json()["build_id"]

    states = {}
    mirror, build = {}, {}
    while time.time() - start < MIRROR_TIMEOUT:
        mirror = session.get("{}/api2/mirror/{}/{}".format(MOLIOR_URL, name, version), timeout=30).json()
        state = mirror.get("state")
        if state not in states:
            states[state] = round(time.time() - start)
            logger.warning("mirror %s/%s: %s after %ss", name, version, state, states[state])
        build = session.get("{}/api2/build/{}".format(MOLIOR_URL, build_id), timeout=30).json()
        if state in ("error", "init_error") or build["buildstate"] in FINAL_STATES:
            break
        children = [session.get("{}/api2/build/{}".format(MOLIOR_URL, c["id"]), timeout=30).json()
                    for c in build.get("children", [])]
        if any(c["buildstate"] in ("build_failed", "publish_failed") for c in children):
            break
        time.sleep(10)

    chroots = [session.get("{}/api2/build/{}".format(MOLIOR_URL, c["id"]), timeout=30).json()
               for c in build.get("children", [])]
    summary = {"mirror": "{}/{}".format(name, version), "build_id": build_id, "seconds": round(time.time() - start),
               "states": states, "buildstate": build.get("buildstate"),
               "chroots": [{k: c.get(k) for k in ("id", "architecture", "buildstate")} for c in chroots]}
    save("mirror-{}-{}.json".format(name, version), summary)
    assert mirror.get("state") == "ready", json.dumps(summary)
    assert build.get("buildstate") == "successful", json.dumps(summary)
    assert chroots and all(c["buildstate"] == "successful" for c in chroots), json.dumps(summary)


def create_project(project, version, basemirror, architectures, repo_url):
    """Creates the project, its projectversion and adds the source repository (molior builds it)."""
    session = molior_session()
    r = session.post(MOLIOR_URL + "/api/projects", json={"name": project}, timeout=30)
    assert r.ok, r.text
    r = session.post("{}/api2/projectbase/{}/versions".format(MOLIOR_URL, project),
                     json={"basemirror": basemirror, "architectures": architectures, "name": version,
                           "description": "deploy test", "dependency_policy": "strict", "cibuilds": False},
                     timeout=30)
    assert r.ok, r.text
    r = session.post("{}/api2/project/{}/{}/repositories".format(MOLIOR_URL, project, version),
                     json={"architectures": architectures, "url": repo_url}, timeout=30)
    assert r.ok, r.text


def wait_for_build(sourcename):
    """Waits until the source build and the deb builds of sourcename are done, fails if one is not successful."""
    session = molior_session()
    start = time.time()
    builds = []
    while time.time() - start < BUILD_TIMEOUT:
        r = session.get(MOLIOR_URL + "/api/builds", params={"search": sourcename, "page": 1, "page_size": 100},
                        timeout=30)
        assert r.ok, r.text
        builds = [b for b in r.json().get("results") if b.get("sourcename") == sourcename
                  and b.get("buildtype") in ("source", "deb")]
        source = [b for b in builds if b["buildtype"] == "source"]
        debs = [b for b in builds if b["buildtype"] == "deb"]
        if any(b["buildstate"] in FINAL_STATES and b["buildstate"] != "successful" for b in builds):
            break
        if source and debs and all(b["buildstate"] == "successful" for b in builds):
            break
        time.sleep(10)
    save("builds-{}.json".format(sourcename), builds)
    states = ["{} {} {}".format(b["id"], b["buildtype"], b["buildstate"]) for b in builds]
    assert builds and all(b["buildstate"] == "successful" for b in builds), \
        "builds of {} after {} s: {}".format(sourcename, round(time.time() - start), ", ".join(states) or "none")


def vboxmanage(*args, check=True):
    """Runs vboxmanage, logs and returns its output; fails with the output if check and the exit code is not 0."""
    r = subprocess.run(["vboxmanage"] + list(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    logger.warning("vboxmanage %s: exit %s\n%s", " ".join(args), r.returncode, r.stdout.strip())
    assert not check or r.returncode == 0, "vboxmanage {}: exit {}\n{}".format(" ".join(args), r.returncode, r.stdout)
    return r.stdout


def vm_info(vm):
    """showvminfo --machinereadable of a VM as a dict."""
    return {k.strip('"'): v.strip('"') for k, _, v in (line.partition("=") for line in vboxmanage(
            "showvminfo", vm, "--machinereadable", check=False).splitlines())}


def vm_running(vm, path, name, what):
    """Fails unless the VM runs, else takes the screenshot <path>.<name>png (name "" or "done." ...)."""
    state = vm_info(vm).get("VMState")
    assert state == "running", "VM of {} {}: {}".format(os.path.basename(path), what, state)
    vboxmanage("controlvm", vm, "screenshotpng", path + "." + name + "png")
    assert os.path.getsize(path + "." + name + "png") > 0, "empty screenshot {}{}png".format(path, name)


def press_enter(vm):
    """Presses and releases Enter on the keyboard of the VM."""
    vboxmanage("controlvm", vm, "keyboardputscancode", "1c", "9c")


def wait_installed(vm, path, disk, dvd):
    """Waits until the installer in the VM is done: it ejects the ISO (the DVD drive is empty), or the disk did not
    grow for INSTALL_IDLE seconds after it grew. Fails after INSTALL_WAIT seconds (screenshot <path>.failed.png)."""
    start, size, idle = time.time(), os.path.getsize(disk), None
    while time.time() - start < INSTALL_WAIT:
        time.sleep(10)
        info = vm_info(vm)
        assert info.get("VMState") == "running", "VM of {} during the installation: {}".format(
            os.path.basename(path), info.get("VMState"))
        if info.get(dvd) in ("emptydrive", "none"):
            logger.warning("installer done after %d s: the ISO is ejected", time.time() - start)
            return
        if os.path.getsize(disk) != size:
            size, idle = os.path.getsize(disk), time.time()
        elif idle and time.time() - idle >= INSTALL_IDLE:
            logger.warning("installer done after %d s: the disk (%d MB) did not grow for %d s",
                           time.time() - start, size // 2**20, INSTALL_IDLE)
            return
    vboxmanage("controlvm", vm, "screenshotpng", path + ".failed.png", check=False)
    raise AssertionError("installer in the VM of {} not done after {} s (disk {} MB), see {}.failed.png".format(
        os.path.basename(path), INSTALL_WAIT, size // 2**20, os.path.basename(path)))


def boot_vm(deployment):
    """Boots a deployment in a VirtualBox VM (headless) and removes the VM. Screenshots and the log of the VM
    (<deployment>.VBox.log) go next to the deployment. VirtualBox runs with its own home (VBOX_USER_HOME), the user's
    VMs are not touched.
    OVA: imported, screenshot <deployment>.png after BOOT_WAIT seconds.
    ISO (installer): a new VM with an empty disk, booting from the disk first and then the ISO. Screenshot
    <deployment>.png after BOOT_WAIT seconds (the hostname question), Enter for the default hostname and Enter to
    confirm the installation; when the installer is done (wait_installed) <deployment>.done.png, Enter to reboot, and
    <deployment>.installed.png of the installed system after BOOT_WAIT seconds.
    Fails if the VM does not start or does not run any more at a screenshot."""
    path = os.path.join(DEPLOY_OUTPUT, deployment)
    vm = "deploy-test-{}".format(os.getpid())
    home = tempfile.mkdtemp(prefix="molior-deploy-vbox-")
    disk = os.path.join(home, vm + ".vdi")
    os.environ["VBOX_USER_HOME"] = home
    try:
        vboxmanage("setproperty", "machinefolder", home)
        if deployment.endswith(".ova"):
            vboxmanage("import", path, "--vsys", "0", "--vmname", vm)
        else:
            vboxmanage("createvm", "--name", vm, "--ostype", "Debian_64", "--register")
            vboxmanage("modifyvm", vm, "--memory", "2048", "--graphicscontroller", "vmsvga", "--boot1", "disk",
                       "--boot2", "dvd", "--boot3", "none", "--boot4", "none")
            vboxmanage("createmedium", "disk", "--filename", disk, "--size", "8192")
            vboxmanage("storagectl", vm, "--name", "SATA", "--add", "sata", "--portcount", "2")
            vboxmanage("storageattach", vm, "--storagectl", "SATA", "--port", "0", "--device", "0", "--type", "hdd",
                       "--medium", disk)
            vboxmanage("storageattach", vm, "--storagectl", "SATA", "--port", "1", "--device", "0",
                       "--type", "dvddrive", "--medium", path)
        vboxmanage("startvm", vm, "--type", "headless")
        time.sleep(BOOT_WAIT)
        vm_running(vm, path, "", "after {} s".format(BOOT_WAIT))
        if deployment.endswith(".iso"):
            press_enter(vm)     # the hostname question: the default (TARGET_HOSTNAME)
            time.sleep(10)
            press_enter(vm)     # "Are you sure to install to /dev/sda ?"
            wait_installed(vm, path, disk, "SATA-1-0")
            vm_running(vm, path, "done.", "at the end of the installation")
            press_enter(vm)     # "press 'Enter' to reboot"
            time.sleep(BOOT_WAIT)
            vm_running(vm, path, "installed.", "{} s after the reboot".format(BOOT_WAIT))
    finally:
        vboxmanage("controlvm", vm, "poweroff", check=False)
        time.sleep(3)
        cfg = vm_info(vm).get("CfgFile")
        if cfg and os.path.exists(os.path.join(os.path.dirname(cfg), "Logs", "VBox.log")):
            shutil.copy(os.path.join(os.path.dirname(cfg), "Logs", "VBox.log"), path + ".VBox.log")
        vboxmanage("unregistervm", vm, "--delete", check=False)   # also deletes the disks of the VM
        os.environ.pop("VBOX_USER_HOME", None)
        shutil.rmtree(home, ignore_errors=True)


DPKG_STATUS = "var/lib/dpkg/status"


def run(*args, **kwargs):
    """Runs a command, fails with its output if the exit code is not 0, returns stdout (bytes)."""
    r = subprocess.run(list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    assert r.returncode == 0, "{}: exit {}\n{}".format(" ".join(args), r.returncode, r.stderr.decode(errors="replace"))
    return r.stdout


def status_from_tar(fileobj, prefix=""):
    """dpkg status file of the root file system in a tar (stream) with the root at prefix."""
    with tarfile.open(fileobj=fileobj, mode="r|*") as tar:
        for member in tar:
            if member.name.lstrip("./") == prefix + DPKG_STATUS and member.isfile():
                return tar.extractfile(member).read().decode()
    raise AssertionError("no {} in the tar".format(prefix + DPKG_STATUS))


def status_from_docker_save(path):
    """dpkg status file of a docker save tar of an image with one layer (docker import of the root file system):
    the layer is the tar in it that contains var/lib/dpkg/status."""
    with tarfile.open(path, mode="r|*") as image:
        for member in image:
            if not member.isfile() or member.size < 1024 * 1024:
                continue   # manifest, config, index json
            try:
                return status_from_tar(image.extractfile(member))
            except (AssertionError, tarfile.TarError):
                continue
    raise AssertionError("no layer with {} in {}".format(DPKG_STATUS, path))


def status_from_disk(raw):
    """dpkg status file of the ext file system on a partition of a raw disk image (read with debugfs, no mount)."""
    table = json.loads(run("sfdisk", "--json", raw))["partitiontable"]
    for part in table["partitions"]:
        r = subprocess.run(["debugfs", "-R", "cat /" + DPKG_STATUS, "{}?offset={}".format(
            raw, part["start"] * table.get("sectorsize", 512))], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if r.returncode == 0 and r.stdout.startswith(b"Package:"):
            return r.stdout.decode()
    raise AssertionError("no partition with {} in {}".format(DPKG_STATUS, raw))


def sparse_copy(src, dst, block=1024 * 1024):
    """Copies a stream into a file, holes for blocks of zeros (a disk image of some GB needs only its used space)."""
    with open(dst, "wb") as out:
        while True:
            data = src.read(block)
            if not data:
                break
            if data.count(0) == len(data):
                out.seek(len(data), os.SEEK_CUR)
            else:
                out.write(data)
        out.truncate()


def dpkg_status(deployment, tmp):
    """The dpkg status file of the root file system of a deployment (by its file name); tmp for temporary files.
    Not for installer and vbox: they are tested by booting them (boot_vm)."""
    path = os.path.join(DEPLOY_OUTPUT, deployment)
    if deployment.endswith("_docker.tar.gz"):
        return status_from_docker_save(path)
    if deployment.endswith("_lxd.tar.gz"):
        with open(path, "rb") as f:
            return status_from_tar(f, "rootfs/")
    if deployment.endswith(".tar.gz"):                       # dir
        with open(path, "rb") as f:
            return status_from_tar(f)
    if deployment.endswith(".img.gz"):                       # image: a disk
        with gzip.open(path, "rb") as f:
            sparse_copy(f, os.path.join(tmp, "disk.raw"))
        return status_from_disk(os.path.join(tmp, "disk.raw"))
    raise AssertionError("unknown deployment type: {}".format(deployment))


def check_packages(deployment, packages):
    """Fails unless all packages are installed in the root file system of the deployment (its dpkg status file)."""
    tmp = tempfile.mkdtemp(prefix="molior-deploy-check-", dir=os.environ.get("MOLIOR_TMPDIR"))
    try:
        status = dpkg_status(deployment, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    installed = {}
    for paragraph in status.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in paragraph.splitlines() if ": " in line and line[0] != " ")
        if fields.get("Status") == "install ok installed":
            installed[fields.get("Package")] = fields.get("Version")
    for package in packages:
        logger.warning("%s: %s %s", deployment, package, installed.get(package, "not installed"))
    missing = [p for p in packages if p not in installed]
    assert not missing, "{}: not installed: {} ({} packages installed)".format(
        deployment, ", ".join(missing), len(installed))
