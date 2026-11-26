# Migration of the 1.4 validation tests

The molior 1.4 validation suite (`molior-testing`, run against an internal test site; not part of this repository)
is ported to `tests/system/valid-1.4/`. This document lists, per test, what differs from the 1.4 original. The
requirements the tests refer to by number are in `docs/requirements-1.4/`.

Rule of the port: test names, ids, metadata, `after` marks, docstrings, logger lines and steps stay as in 1.4. Only the
values that pointed to the old site and the helpers that used the old interfaces change.

## Overview

1.4 has 30 tests. 27 are ported, in the 1.4 file order. All 27 pass in the 1.5 system tests except `test_mirror`,
which is skipped without its environment variables (26 passed, 1 skipped in 912 s, exit 0, after the molior fixes
in "molior changes the port needed"). Tests 26 and 27 (arm) run the arm builds with qemu on the amd64 node of the
test cluster.

| # | Test | Id | Status | Change in the test function |
|---|---|---|---|---|
| 1 | `test_basemirror_creation` | dbcf79da | ported | mirror source, keys, architectures, filter |
| 2 | `test_build_parallelization` | c0588942 | ported | aptly URL; wait list uses source package names |
| 3 | `test_build_output` | 4a919a48 | ported | aptly URL only |
| 4 | `test_schroot_creation` | c1c240a6 | ported | checks the build container image instead of the schroot tarball |
| 5 | `test_repository_location` | f84a5354 | ported | `kubectl exec` instead of SSH; no systemd |
| 6 | `test_api` | 8a89f528 | ported | none (suite: base mirror `13`) |
| 7 | `test_aptly` | 8cd64879 | ported | none |
| 8 | `test_projectversion_delete` | b8f486cc | ported | none (suite: polling instead of delays) |
| 9 | `test_projectversion_clone` | 681288e5 | ported | none (suite: polling, no extract of the clone id) |
| 10 | `test_projectversion_overlay` | c6b970e6 | ported | none (suite: polling) |
| 11 | `test_projectversion_dependency_edit` | 375cd781 | ported | none |
| 12 | `test_projectversion_search_and_sort` | e34fe8d2 | ported | none |
| 13 | `test_projectversion_repository_delete` | 99106b79 | ported | none |
| 14 | `test_mirror` | f58bdeb5 | ported | URLs from environment variables, skipped without them |
| 15 | `test_successful_build` | a201b9df | ported | build log read in the molior container; new marker |
| 16 | `test_failed_build` | 6b0e3946 | ported | build log read in the molior container; new marker |
| 17 | `test_build_log` | cec29475 | ported | build log read in the molior container; `kubectl exec` instead of SSH |
| 18 | `test_build_order` | 4b46b62f | ported | indentation only |
| 19 | `test_role_based_access` | 348c848a | ported | none (suite: a local test user instead of an LDAP user) |
| 20 | `test_multi_project_builds` | 3c84a262 | ported | aptly URL; wait for the source package name `cipackage`; ignores older builds |
| 21 | `test_mono_build` | 4bdcb6d8 | ported | public git URL; longer wait |
| 22 | `test_git_lfs_build` | 2872bce4 | ported | public git URL |
| 23 | `test_submodule_build` | d2a19958 | ported | public git URL |
| 24 | `test_dotnet_core_mirror` | 08347517 | ported | public Microsoft repository, filter on one SDK |
| 25 | `test_dotnet_core_project` | 91afb195 | ported | longer wait (suite: dependency `dotnet-core/11.0`) |
| 26 | `test_arm_build` | 6dc6c29d | ported | creates its own base mirror `trixie-arm/13` (suite: that base mirror, public git URL); arm builds with qemu on the amd64 node, longer wait |
| 27 | `test_buildvariant_filter` | a671b2ec | ported | none |
| - | `test_cleanup` | 4643c05a | obsolete | every run uses a new cluster |
| - | `test_build_notification` | 1a8ebb57 | obsolete | build notification hooks are removed in 1.5 |
| - | `test_molior_deploy` | 4643c058 | ported to `tests/deploy/` | not in this suite; separate suite `tests/deploy/`, pytest on the runner host (not run yet) |

## Changes that apply to all tests

### How the tests run
- **1.4:** pytest ran against a deployed molior and aptly. The hosts came from `testconfig.yaml`. The tests used SSH to
  the molior and aptly hosts (`molior_ssh_run`, `aptly_ssh_run`), and pyresttest for the yml API suites.
- **1.5:** `tests/system/system-tests.sh` creates a throwaway k3d cluster per run, with molior, aptly, a registry and a
  test runner pod. pytest runs in the runner pod. URLs and the admin password come from environment variables
  (`MOLIOR_URL`, `APTLY_URL`, `APTLY_API_URL`, `MOLIOR_ADMIN_PASSWORD`).
- **SSH becomes `kubectl exec`:** `molior_exec` runs a command in the molior server container and `aptly_exec` runs one
  in the aptly server container. The runner pod has a service account with a Role for `pods/exec`, but only in the
  test cluster.
- **pyresttest becomes Python:** each yml file in `tests/api-tests/` becomes one function in `api_tests.py`, with the
  same step names, requests and checks. `SUITES` maps the yml paths to the functions, so the calls in
  `validation_tests.py` keep the yml paths. Details are in "The API suites" below.
- **The order** is the file order. The 1.4 `first` and `after` marks are kept as metadata only. In 1.4 they never
  defined the order either: two `after` marks name tests that do not exist (`test_build_short`,
  `test_failed_build_short`).
- **Timeouts fail the test.** Every wait in the helpers fails the test when its time is over: `create_mirror`
  (`MIRROR_TIMEOUT`, 1500 s), `wait_for_paralell_builds` (`BUILD_TIMEOUT`, 1200 s), `get_build` (300 s, or
  `BUILD_TIMEOUT` for mono and dotnet), `get_build_log` (60 s), and `poll` in the suites (120 s). On top of that,
  each test has a limit of `TEST_TIMEOUT` (pytest-timeout, default 3600 s); a test that reaches it fails and the
  run goes on. The whole run has a limit of `RUN_TIMEOUT` (default 14400 s). 1.4 had no limit per test.
- **The result line** shows the test number, the location, the result, the time and the percentage. This needs `-v`.

### The 1.4 setup
- **1.4 test site:** a molior test server, an aptly test server, an internal git server with the test repos, two intel
  build nodes and one arm build node. The base mirror was an internal Debian mirror (read only).
- **1.4 run:** `run-tests.sh` installed a systemd override for `molior-server` (`--coverage`), restarted it and called
  `tox` (py37, deps from `requirements.txt`), which called `run.sh`. `run.sh` wrote `testconfig.yaml` with the 5 hosts
  and ran `pytest validation_tests.py -v --junitxml=results/molior.testreport.<molior-server version>.xml`. After the
  run the server was restarted to write the coverage.
- **Metadata:** each test has a `metadata` mark (id, author, reviewer, review date, requirement numbers like `000`
  to `016` and `200`, see `docs/requirements-1.4/`). The fixture `add_function_properties`, which wrote the start and
  end time and the docstring as junit properties, was already commented out in 1.4.
- **1.5:** `system-tests.sh` writes `junit.xml`, the logs of the molior, postgres and aptly containers, the build
  output and the server coverage (`coverage-report.txt`, `coverage.xml`) to `RESULTS_DIR`. The `metadata`, `first`
  and `after` marks are kept and registered in `pytest_configure` (`conftest.py`); nothing writes the metadata into
  the junit xml.

### Values
- **Base mirror:** `stretch/9.3` becomes `trixie/13` (`basemirror`, `basemirror_version`). The published repos are
  under `<aptly_url>/trixie/13/...` instead of `<aptly_url>/stretch/9.3/...`.
- **Git repos:** the internal git server (SSH URLs, cloned with a deploy key) is replaced by the public repos `https://github.com/molior-dbs/test-<name>.git`. They are cloned over HTTPS without a key. Each repo
  has one commit and one tag, and is updated for trixie. Package names and `debian/molior.yml` are unchanged, except
  the `build_after` entry of `test-tick` (1.4: `track`, now `test-track`, because molior matches it against the last
  part of the repo URL). Details are in "The test repos" below.
- **User:** the tests log in as `admin`. The 1.4 tests used a fixed test user.

### Helpers (`utils.py`)
- `create_mirror` uses `POST /api2/mirror`, which takes the base mirror as `name/version` instead of an id. It adds the
  arguments `mirror_filter` and `filter_with_deps`. It waits for the mirror, and for a base mirror also for the build
  environments. It fails on an error state; 1.4 returned 1 and the test went on. It writes the timings to
  `RESULTS_DIR`.
- `get_build` sends `search`, `page` and `page_size`. In 1.4 the parameters went into `str.format()` by mistake, so the
  API got none and returned only the newest 10 builds. **It does not wait for a build that has ended:** with a
  build state, it fails at once when all builds of the package have ended in another state, and for deb builds when
  the newest source build of the package has failed (its deb builds do not build). 1.4 waited until the timeout.
- `wait_for_paralell_builds` sends `page_size=100` (1.4 sent `pagesize`, which the API ignores) and waits up to
  `BUILD_TIMEOUT` (default 1200 s; 1.4 waited 600 s). It takes `ignore_ids`, so that builds of an earlier test can be
  skipped. **It fails on a timeout** and names the builds that are not done. 1.4 returned what it had found and the
  test went on. It takes all end states as done (1.4: `successful`, `build_failed` and `nothing_done`, so a
  `publish_failed` build waited until the timeout), and it fails at once when the newest source build of a package
  has failed.
- The end states are `FINAL_STATES` in `utils.py`. Not detected: a build that fails before its source build is
  created (git clone, `debian/changelog`); the wait for it ends at the timeout.
- `molior_session` logs in as `admin` with `MOLIOR_ADMIN_PASSWORD`. 1.4 logged in the fixed test user.
- **Dropped helpers:** `get_random_word` (unused), `ssh_run` (no SSH), `wait_or_kill` (websocket listener),
  `run_api_tests` and `execute_build_test` (pyresttest; `api_test` and `build_test` call `api_tests.py`).
- **New helpers:**
  - `get_build_log` reads `/var/lib/molior/buildout/<id>/build.log` in the molior container and waits up to 60 s for a
    marker. The server writes the log through a queue, so the end of the log can come after the state change. It
    fails on a timeout and shows the end of the log.
  - `get_deb_build_ids` returns the ids of the deb builds of the given source packages.
  - `pull_image` pulls files from an image in the build registry (registry API v2).
  - `latest_package_version` reads the newest version of a package from an APT `Packages` index.

### Fixtures (`conftest.py`)
- **Kept:** `molior_url`, `aptly_url`, `aptly_api_url`, `project_name` (`molior-validation`), `project_version` (`1`),
  `api_vars`, `api_test`, `aptly_api_test`, `build_test`, `get_project_vars`, `create_mirror`, `get_basemirror`,
  `get_build_id`.
- **New:** `molior_exec` and `aptly_exec`, which replace `molior_ssh_run` and `aptly_ssh_run`. The hook
  `pytest_configure` registers the marks `metadata`, `first` and `after` (1.4 used pytest plugins for them, see
  `requirements.txt`).
- **Dropped:**
  - `molior_ssh`, `aptly_ssh`, `ssh_key_path`, `user`, `password`: there is no SSH, and the tests use the admin.
  - `project2_name` to `project4_name`, `project_version_2`: unused.
  - `websocket_server`, `wait_or_kill`: unused, as the websocket listener was already commented out in 1.4.
  - The `hook_body` in `api_vars`, which only the obsolete notification test used.
  - `prepare_test_repo`: unused in 1.4. It cloned `multiproject` from the internal git server with a deploy key and
    wrote a `debian/molior.yml`.
  - `add_function_properties`: already commented out in 1.4 (see "The 1.4 setup").
- `api_vars` and `get_project_vars` return a dict instead of a JSON string for pyresttest. `get_project_vars` also has
  the URLs and the admin login of `api_vars`.
- `build_test` returns what the suite returns. Only `ci-build.yml` returns something, the build id.

### 1.4 files that are not ported
- `tests/api-tests/*.yml`: replaced by `api_tests.py` (see "The API suites").
- `run-tests.sh`, `run.sh`, `tox.ini`, `requirements.txt`, `molior-server.service.d-override.conf`: the 1.4 runner
  (see "The 1.4 setup"). `system-tests.sh` replaces it.
- `tests/webserver.py`: a Flask receiver for the notification hooks of the obsolete `test_build_notification`.
- `tests/websocket-test.py`: a websocket listener that checked the build state sequence; already commented out in
  1.4 (fixture `websocket_server`).
- `tests/test-deploy.sh`: copied unchanged to `tests/deploy/test-deploy.sh` (used by `test_molior_deploy`).
- SSH keys for the 1.4 hosts (two directories and a submodule). Not copied (secrets).
- `README.md`: the 1.4 installation of the test site.

## molior changes the port needed

The tests found these molior bugs. The tests themselves were not changed for them.
- **Filter with dependencies for mirrors** (`4a5d6749`, upgrade 68): `FilterWithDeps` for aptly, so that the base
  mirror of test 1 can be filtered to a small set of packages with their dependencies.
- **Kubernetes Job name** (`23b64f09`): a CI build version like `0.0.1+git<date>.<hash>` gave an invalid Job name
  (`+`), so the deb build of `cipackage` failed at once (test 2). `build_job_name()` makes a valid name.
- **git-lfs race** (`e3866687`): every clone ran `git lfs install`, which writes the global `~/.gitconfig` of the
  molior user. Parallel clones raced for its lock (`could not lock config file`), so the clone of `test-tick` failed
  and test 2 waited until its timeout. `GitClone` runs `git lfs install --local` per clone.
- **Clean build environment** (`27e2a1fb`): the build Job variables (`PLATFORM=trixie`, `BUILD_TOKEN`, ...) leaked
  into the package build. MSBuild and xbuild read `PLATFORM` as the `Platform` property, so keepass2 (test 21) and
  mira-test (test 25) failed. `docker-build` now runs `dpkg-buildpackage` and `lintian` with `env -i` and only
  `PATH`, `USER`, `LOGNAME`, `SHELL` and `HOME`.

## The test repos

The 14 repos of the 1.4 tests are all in the GitHub organisation `molior-dbs`. Each has one commit `Initial commit`
and one annotated tag `v<version>` (`~` becomes `-`) on `main`, with author, committer and tagger
`Molior Test <test@molior.info>`.

| 1.4 repo | GitHub repo | Source package | Tag | Used by |
|---|---|---|---|---|
| track | `test-track` | track | v0.0.1 | tests 2 (`init-testproject.yml`), 3, 15, 18 |
| tick | `test-tick` | tick | v0.0.2 | tests 2, 3, 13, 18 |
| trick | `test-trick` | trick | v0.0.1-alpha2 | tests 2, 3, 17 |
| badtrick | `test-badtrick` | badtrick | v0.0.0 | test 2 (must build nothing) |
| badtrack | `test-badtrack` | badtrack | v0.0.1 | tests 2, 16 |
| testproject | `testproject` | testproject | v3.0.12 | tests 2, deploy |
| ci-build | `test-ci-build` | cipackage | v0.0.1 | tests 2, 20; submodule of `test-submodule` (test 23) |
| build-notifications | `test-build-notifications` | build-notify-package | v0.0.1 | test 2 |
| multiproject | `test-multiproject` | multiproject | v0.0.1 | test 20 |
| mono-test | `test-mono` | keepass2 | v2.33-3 | test 21 |
| git-lfs-kitten-test | `test-git-lfs` | git-lfs-test | v0.0.3 | test 22 |
| submodule-test | `test-submodule` | submodulepackage | v0.0.1 | test 23 |
| dotnet-core-test | `test-dotnet-core` | mira-test | v1.0.6 | test 25 |
| arm-build | `test-arm` | armpackage | v0.0.1 | tests 26, 27 |

**Changes in all repos:**
- `Maintainer: Molior Test <test@molior.info>` (1.4: personal company addresses; `test-mono`: the Debian CLI
  team, and the `Uploaders` field is removed).
- `debian/changelog` has one entry, distribution `trixie` (1.4: `jessie` or `stretch`).
- `debian/compat` (9) is removed, `Build-Depends: debhelper-compat (= 13)` (1.4: `debhelper (>= 8)` or `(>= 9)`),
  `Standards-Version: 4.7.2`, `Priority: optional` (1.4: `extra` in some).
- `debian/copyright`: Apache-2.0, "The Molior Authors" (1.4: a company copyright with an internal-use-only clause, or
  no file). `test-mono` keeps the GPL-2+ copyright of keepass2 and adds the Molior Authors for `debian/*`.
- A short `README.md` with the purpose of the repo.
- Source format `3.0 (native)`, `test-mono` `3.0 (git)`, as in 1.4.
- `debian/molior.yml` is unchanged (targets `molior-validation` with `1`, `prj1`/`prj2`, `mono`, `git-lfs`,
  `submodule`, `dotnet`, `arm-test`), except `build_after` of `test-tick`.

**Changes per repo:**
- `test-track`, `test-badtrack`: the short test runs with `python3 -m unittest -v tests/unit.py` (1.4: `py.test`
  with `python-pytest`, gone since bullseye). The short test stays for requirement 012 "Short Test Run".
- `test-tick`: `build_after: ['test-track']` (1.4: `track`).
- `testproject`: `policykit-1` becomes `polkitd`, `xserver-xorg-video-modesetting` is removed (both not in trixie),
  the description and a comment line in `deploy/dir.conf` named internal products; the description is neutral now and
  the comment is removed. `deploy/` is kept.
- `test-submodule`: `.gitmodules` points to `https://github.com/molior-dbs/test-ci-build.git` (1.4: an SSH URL of
  the internal git server), pinned at `f2b79d9` (v0.0.1). HTTPS, so that molior clones it
  without a key.
- `test-mono` (keepass2 2.33-2 becomes 2.33-3): `python3` and `python3-pkg-resources` instead of `python`, the
  archmage module `archmage.CHM.CHM` instead of `archmod.CHM.CHMDir`, `dh $@ --with=cli` instead of
  `include /usr/share/cli-common/cli.make`, `cli-common-dev (>= 0.8~)`, `export MONO_DISABLE_SHM = 1`,
  `Rules-Requires-Root: no`. The dead `Vcs-*` fields (alioth) are removed.
- `test-dotnet-core` (mira-test 1.0.5 becomes 1.0.6): `dotnet-sdk-11.0` and `dotnet-runtime-11.0` (1.4:
  `dotnet-sdk-2.1.3`, `dotnet-runtime-2.0.4`), `net11.0` (1.4: `netcoreapp2.0`), install to `/opt/mira-test`
  (1.4: an internal path), `dotnet build --disable-build-servers`, `DOTNET_NOLOGO=1`, `/bin` in `.gitignore`,
  `Rules-Requires-Root: no`, a new description.
- `test-git-lfs`: `kitten.jpg` is in git LFS. Open: its licence (from Wikimedia Commons, not checked).
- `test-badtrick`: still no `debian/molior.yml`, so it builds nothing.

**Checked:** the first 12 repos (all but `test-mono` and `test-dotnet-core`) build with `dpkg-buildpackage` in a
trixie container (`test-badtrack` fails in its short test as intended, `test-arm` built for amd64 only). `test-mono`
and `test-dotnet-core` were checked in the system tests (tests 21 and 25). All 13 repos of the ported tests build in
the system tests. Arm builds of `test-arm` by molior are not checked.

## The tests

### 1. `test_basemirror_creation`
- The mirror source is `http://deb.debian.org/debian/`. 1.4 used an internal Debian mirror.
- The key comes from `hkp://keyserver.ubuntu.com:80` with the Debian archive keys `762F67A0B2C39DE4`,
  `78DBA3BC47EF2265` and `6ED0E7B82643E131`. 1.4 used the armored key URL of the internal mirror.
- Architectures: `amd64` only. 1.4 had `amd64,armhf,arm64` for test 26 (a projectversion can only have architectures
  of its base mirror). Here test 26 creates its own base mirror with the arm architectures, so the arm build
  environments (made with qemu, about 9 minutes) are not made in the first test (101 s instead of 712 s).
- New: `mirror_filter=basemirror_filter` and `filter_with_deps=True`. The filter keeps the mirror small. It contains
  the required packages and `apt`, `build-essential` and `ca-certificates`. It adds the tools of the build environment
  (`fakeroot`, `eatmydata`, `lintian`, `devscripts`, `curl`, `git`, `passwd` and more) and the build dependencies of the
  test packages:
  - all tests: `debhelper`, `python3`
  - `test-mono` (keepass2): `archmage`, `cli-common-dev`, `imagemagick`, `libmono-cil-dev`, `mono-devel`, `mono-xbuild`,
    `python3-pkg-resources`
  - the dotnet packages: `libicu76` and `libgssapi-krb5-2`
  - aptly adds their dependencies.

### 2. `test_build_parallelization`
- The aptly repo URL uses `basemirror`/`basemirror_version` instead of the fixed `stretch/9.3`.
- **The wait list** has the source package names: `build-notify-package`, `cipackage`, `testproject`, `badtrack`, `trick`,
  `tick` and `track`. 1.4 had the repo names `build-notifications` and `ci-build`, and `badtick` (a name that exists
  nowhere). Deb builds carry the source package name, so the 1.4 wait never finished and always ran into its
  timeout. `badtrick` is not in either list: it has no `debian/molior.yml` and builds nothing.
- The unused fixture `wait_or_kill` is removed from the signature.
- One long `assert` line is split (flake8).
- **Suite `init-testproject.yml`:** base mirror `trixie/13`; the 8 repos use the public URLs. The 7
  "Add Sourcerepository" steps are written as a loop with the same names, order and bodies.

### 3. `test_build_output`
- The aptly `Packages` URL uses `basemirror`/`basemirror_version` (in the log line and the request). Nothing else
  changes.

### 4. `test_schroot_creation`
- 1.4 ran `ls -l /var/lib/schroot/chroots/stretch-9.3-amd64.tar.xz` on the molior host over SSH.
- 1.5 has no schroot. The build environment is a container image per base mirror and architecture,
  `molior/<base>-<arch>:<version>`. `create-docker.sh` builds it, and it is pushed to the registry of the build
  backend.
- The test reads the registry from `/etc/molior/backend-kubernetes.yml` in the molior container. It pulls
  `molior/trixie-amd64:13` like a build node does (`pull_image`), and checks:
  - the image architecture is `amd64`
  - `/etc/os-release` has `VERSION_ID="13"` (it is a symlink to `../usr/lib/os-release`, which is followed)
  - the build script `/app/docker-build` exists
  - `/usr/bin/dpkg-buildpackage` (build-essential) exists
  - `/etc/passwd` has a `build` user
- The fixture `molior_ssh_run` is replaced by `molior_exec`.

### 5. `test_repository_location`
- 1.4 ran `sudo systemctl status aptly` and `aptly config show | grep -i rootdir` over SSH on the aptly host.
- 1.5 runs aptly in the aptly pod, which has no systemd. The test checks that the process in `/tmp/aptly.pid` is alive
  (`kill -0`). It also checks `aptly config show` as the user `aptly` for the root dir; the grep accepts both
  `root_dir` and `rootdir`.
- The fixture `aptly_ssh_run` is replaced by `aptly_exec`.

### 6. to 13. The API tests
`test_api`, `test_aptly`, `test_projectversion_delete`, `test_projectversion_clone`, `test_projectversion_overlay`,
`test_projectversion_dependency_edit`, `test_projectversion_search_and_sort` and `test_projectversion_repository_delete`
are unchanged. Their changes are in the suites, see "The API suites" below.

### 14. `test_mirror`
- 1.4 mirrored a small repository from an internal server (`citizen` 1.2.2-0, one package), signed with the key of
  that server.
- The port mirrors a copy of that repository: `tests/system/ctzpos-cups.tar.xz` (git lfs) is extracted into the test
  runner image and served by the test runner pod (`system-tests.sh`, service `ctzpos-cups`). The URLs are fixed in the
  test: `http://ctzpos-cups/` (repository root) and `http://ctzpos-cups/repo.asc` (armored key). The test is not
  skipped any more.
- Name, version, distribution, component and architecture are unchanged. The base mirror is `trixie/13`, and the check
  URL uses `basemirror`/`basemirror_version`.
- Open: the copy is still signed with the key of the internal server; it needs its own test key.

### 15. `test_successful_build`
- 1.4 read `/buildout/<id>/build.log` over HTTP and checked for `Status: successful`. 1.5 serves no `/buildout/` over
  HTTP and writes no `Status:` line.
- The test reads the log in the molior container (`get_build_log`) and checks for the title `molior: Done`, which ends
  a successful deb build log.

### 16. `test_failed_build`
- The log is read in the molior container, as in test 15.
- The marker is `molior: Building failed`, the title the 1.5 build script writes. 1.4 checked
  `Error: sbuild command failed`; 1.5 has no sbuild.
- The assert message used the undefined names `buildstate` and `buildname` (a NameError in 1.4 if the build was not
  found, flake8 F821). The values `"build_failed"` and `"badtrack"` are filled in.

### 17. `test_build_log`
- The log is read in the molior container and the check is `molior: Done`, as in test 15.
- The 1.4 comment "verify that the build has failed" and its message are kept, although the test checks a successful
  build. This copy error is in 1.4 too.
- The check that `/var/lib/molior/buildout/<id>/build.log` exists uses `molior_exec` instead of `molior_ssh_run`.

### 18. `test_build_order`
- Only the indentation of the assert message is changed (flake8). The test still checks that `tick` started after
  `track` ended (`build_after`).

### 19. `test_role_based_access`
- The test function is unchanged.
- **Suite `rolebasedaccess.yml`:** 1.4 logged in an existing LDAP user with a password in the yml. That user name is
  internal, and the password is not copied.
  - The admin first creates the local user `testuser` (`POST /api/users`, `testuser@example.com`), with a random
    password from `secrets.token_urlsafe`. This works with the db auth backend of the test cluster.
  - Then the 4 yml steps run with unchanged names. "Login with LDAP user" logs in as the local user. Then the admin
    adds the user to the project as `owner` and removes it again.
  - As in 1.4, the user is not deleted afterwards, and the test checks no access control.

### 20. `test_multi_project_builds`
- Before the suites run, the test reads the ids of the existing `cipackage` and `multiproject` deb builds
  (`get_deb_build_ids`). The wait ignores them (`ignore_ids`). `cipackage` was already built by test 2, so without this
  the wait would see the old build.
- **The wait and the check** use the source package name `cipackage` instead of the repo name `ci-build`. 1.4 never
  found the CI build and always ran into its timeout.
- New check: both `cipackage` and `multiproject` builds are found.
- The aptly `Packages` URLs of `prj1` and `prj2` use `basemirror`/`basemirror_version`.
- **Suite `ci-build.yml`:**
  - The `git_ref` is `f2b79d9282f7095acfa5c3d537148f0ad77f6aee` and the `git_branch` is `main`. The 1.4 ref and the
    branch `validation` do not exist in the public repo.
  - The repository URL must be exactly the URL that `init-testproject.yml` added, because molior looks the repo up by
    its URL.
  - The suite returns the build id. 1.4 ignored the response, and the test does not use it.
- **Suite `multi-project.yml`:** base mirror `trixie/13` and the public URL of `test-multiproject`.

### 21. `test_mono_build`
- The repo URL is `https://github.com/molior-dbs/test-mono.git`.
- `get_build` waits up to `BUILD_TIMEOUT` (default 1200 s). 1.4 used the default 300 s, and the keepass2 build takes
  longer.
- **The package `test-mono`** is the Debian keepass2 2.33 package, built with mono. It is updated for trixie (only
  `debian/` changed) to version `2.33-3`:
  - `python3` replaces `python`, and `python3-pkg-resources` is added.
  - The archmage module name is changed.
  - `debhelper-compat (= 13)` and `dh --with=cli` replace the old helpers.
  - Source format `3.0 (git)` is kept. molior checks out the tag `v2.33-3` to build.
- **Mono comes from the base mirror, as in 1.4.** The projectversion `mono` has no dependency. In 1.4 the mono
  packages (mono 4.6.2) came from the Debian stretch base mirror. Now they come from the trixie base mirror (mono
  6.12), so they are in its filter (test 1).
- The docstring "Test a build using the mono mirror" is kept from 1.4, but no mono mirror is used, in 1.4 or now.
  A script that mirrored the upstream mono repository existed while the test was written, but it was never part of
  the test and was removed right after. The same docstring is also on tests 22 and 23, which use no mirror.

### 22. `test_git_lfs_build`
- The repo URL is `https://github.com/molior-dbs/test-git-lfs.git`. Nothing else changes.

### 23. `test_submodule_build`
- The repo URL is `https://github.com/molior-dbs/test-submodule.git`. Nothing else changes. The submodule points to
  `https://github.com/molior-dbs/test-ci-build.git`.

### 24. `test_dotnet_core_mirror`
- 1.4 mirrored an internal frozen copy of the Microsoft repository for stretch (`dotnet-core` `2.1.3`, distribution
  `stretch`, 24 package versions), completely and without a filter.
- 1.5 mirrors the public Microsoft repository:
  - `https://packages.microsoft.com/debian/13/prod/`, distribution `trixie`, component `main`, architecture `amd64`
  - key `https://packages.microsoft.com/keys/microsoft-2025.asc`
  - mirror name `dotnet-core`, version `11.0` (`dotnet_mirror_version`)
- The repository is large (about 27 GB for amd64) and has every SDK version. So the mirror has the filter
  `dotnet-sdk-11.0 (= <version>)` with dependencies, which is one SDK with its runtime packages.
  - The test reads the newest `dotnet-sdk-11.0` version from the `Packages` index of the repository when it runs
    (`latest_package_version`).
  - The Debian dependencies (`libicu76`, krb5) come from the base mirror (test 1).
- The check URL uses `basemirror`, `basemirror_version`, the mirror version and the distribution `trixie`.

### 25. `test_dotnet_core_project`
- `get_build` waits up to `BUILD_TIMEOUT` (default 1200 s), as in test 21.
- **Suite `dotnet-core-project.yml`:** base mirror `trixie/13`, the dependency `dotnet-core/11.0` (was `2.1.3`) and the
  repo `https://github.com/molior-dbs/test-dotnet-core.git`. The step names are kept, including "Create mono
  Projectversion".
  - The mirror version `11.0` is written in both the suite and `validation_tests.py`, so a change must be made in both
    places.
- **The package `test-dotnet-core`** (`mira-test` 1.0.6) is a C# hello world. It is updated from .NET Core 2.0 to .NET
  11 (`dotnet-sdk-11.0`, `net11.0`) and installs to `/opt/mira-test`.
  - It builds offline without NuGet. It runs `dotnet build` with `--disable-build-servers`, because the build server
    made builds fail without an error.

### 26. `test_arm_build`
- New: it first creates the base mirror `trixie-arm/13` (dist `trixie`, `amd64,armhf,arm64`, the same source, keys
  and filter as test 1) with `create_mirror`. 1.4 used its first base mirror, which had these architectures. The arm
  build environments are made in the molior pod with qemu, so the host needs qemu binfmt handlers with the `F` flag.
  Their images are `molior/trixie-arm-<arch>:13`, apart from those of `trixie/13`. `tests/system/values.yaml` sets
  `molior.maxParallelChroots: 3` (was 1), so the three build environments are made at the same time.
- molior runs arm64 and armhf deb builds in build pods with the node selector of the arm64 queue
  (`builder.arm64.nodeLabel`, default `kubernetes.io/arch=arm64`). The test cluster has no arm node, so
  `tests/system/values.yaml` sets `builder.arm64.nodeLabel: kubernetes.io/arch=amd64`: the arm build pods run on the
  amd64 node, and the arm binaries in them run through qemu (binfmt `F` flag, see above).
- `get_build` waits up to `BUILD_TIMEOUT` (default 1200 s; 1.4: 300 s), builds under qemu are slower.
- Without that setting and without an arm node, molior fails the builds at once
  (`no node with label kubernetes.io/arch=arm64 in the cluster`), and `get_build` fails right after
  (`deb build of armpackage not successful: ...`). Seen in two runs before the setting; the unit tests in
  `tests/unit/molior/test_kubernetes_job.py` cover it.
- The package builds for amd64, arm64 and armhf (checked with qemu, outside molior).

### 27. `test_buildvariant_filter`
- Unchanged. It searches the builds for `armhf armpackage` and `arm64 armpackage` (3 each: the deb build, its source
  build and the top build, because the search adds parent and grandparent builds) and for `invalid` (0). It counts
  builds in any state, so it does not need the arm builds to finish.

## The API suites

The yml files of `tests/api-tests/` are not read and not in the test image. `api_tests.py` has one function per file.

### Differences in all suites
- **Session:** each suite uses one `requests.Session`, which sends the login cookie. The yml took the `Set-Cookie`
  header and sent it as `Cookie`. The effect is the same.
- **Content-Type:** the port sends `application/json` when a step has a body. So the login and add-repository steps
  now send it (the yml sent none), and GET and DELETE steps without a body no longer send it.
- **Expected status:** where the yml has no `expected_status`, any 2xx is accepted (the pyresttest default). Not checked
  against pyresttest.
- **Failure:** a suite stops at the first failed step, with the step name, status and response body. pyresttest ran
  the whole file and the test failed afterwards (`check=True`).
- **Timeout:** each request has a timeout of 60 s. The yml `config` blocks (`testset`, `timeout: 100`, an unused
  `generators` entry) are dropped.
- **Delays:** a yml `delay` before a step that waits for an async aptly operation becomes polling, every 2 s for at
  most 120 s. The yml checked once after a fixed 10 s, so the port can pass earlier and waits longer.
- **Checks:** pyresttest validators (`compare`, `str_eq`, `eq`) are Python `assert`s with the same meaning. Values
  from `extract_binds` that the next steps use become local values. Unused extracts are dropped.
- **Logging:** each step is logged with `api test step: <name>`.
- **Values:** `stretch/9.3` becomes `trixie/13`, the git URLs become the public ones, and the login is the admin.

### Per suite
- **`init-testproject.yml`** (test 2): see test 2. The two checks of "Get Projectversion" (`name`, `project_name`) are
  `assert`s.
- **`get-tests.yml`** (test 6):
  - The base mirror check looks for the name `13` instead of `9.3`.
  - The check is now stricter. The yml compared the result list with `not_equals None`, and YAML reads `None` as the
    string `'None'`, so the 1.4 check could never fail. The port fails when there is no base mirror `13`.
  - The unused extract `basemirror_id` is dropped.
- **`aptly.yml`** (test 7): same step: `POST /` on the aptly API without login gives 401. The URL comes from
  `APTLY_API_URL` (default `http://aptly:3143`, the nginx with basic auth in front of the aptly API).
- **`delete-projectversion.yml`** (test 8): the three delayed steps poll:
  - "Creation of ProjectVersion on aptly", until 200
  - "Delete the ProjectVersion for good", until 2xx
  - "Test deletion of ProjectVersion on aptly", until 404
  The aptly URLs use `trixie/13`.
- **`clone-projectversion.yml`** (test 9):
  - The extract of `id` and `name` of the clone is dropped: the 1.5 copy returns `build_id` and `rebuild_ids`, and the
    yml never used the values.
  - The three `str_eq` comparisons with the original are compared as strings.
  - The aptly check polls.
  - The step names keep the 1.4 typos.
- **`overlay-projectversion.yml`** (test 10): the comparison of `basemirror` is a string comparison, and the aptly check
  polls.
- **`edit-dependencies.yml`** (test 11): base mirror of the clone `trixie/13`; the checks are `assert`s. No delays.
- **`sorted.yml`** (test 12): only the login step, because the sort check is commented out in 1.4 too. The function is
  called `sorted_projectversions`.
- **`delete-repository.yml`** (test 13): the repo `tick` is `test-tick`. The extract `sourcerepo_id` becomes a local
  value.
- **`rolebasedaccess.yml`** (test 19): see test 19.
- **`ci-build.yml`** and **`multi-project.yml`** (test 20): see test 20. `multi-project.yml` keeps `"startbuild": false`
  for `prj2`.
- **`create-project.yml`** (tests 21 to 23):
  - Base mirror `trixie/13`; the repo URL comes from `get_project_vars`.
  - The extracts `projectversion_id` and `projectversion_name` become `assert "id" in data` and the name for the next
    URL. The `assert` is new.
- **`dotnet-core-project.yml`** (test 25): see test 25.
- **`arm-project.yml`** (test 26): base mirror `trixie-arm/13` (made by test 26), the repo
  `https://github.com/molior-dbs/test-arm.git`. The projectversion `arm-test` has `armhf`, `arm64` and `amd64`, the
  repo `arm64` and `armhf`, as in 1.4.
- **`buildvariant-filter.yml`** (test 27): the URL gets a leading `/` (`/api/builds`). The three
  `total_result_count` checks are `assert`s.
- **Not ported:** `cleanup.yml`, `add-notification-hook.yml` and `trigger-notify-build.yml` belong to obsolete tests.

## Not ported

- **`test_cleanup`** (4643c05a): obsolete. It deleted the test data of an earlier run, and every run now uses a new
  cluster.
- **`test_build_notification`** (1a8ebb57): obsolete. The build notification hooks are removed in 1.5.
- **`test_molior_deploy`** (4643c058): not in this suite, ported to the separate suite `tests/deploy/` (2026-11-26,
  written, not run). It tests molior-deploy (molior-tools) against molior, so it runs on the runner host (root, loop
  devices, nbd, docker, virtualbox), not in a pod. Changes:
  - `tests/deploy/deploy-tests.sh`: own k3d cluster, NodePorts 30080 (web) and 30088 (repo) mapped to free host
    ports, `aptly.publicUrl` set to the host repo port (molior-deploy takes the APT sources from `aptsources`, the
    builds in the cluster use `internalUrl`), pytest on the host.
  - Two setup tests in front (no 1.4 metadata): `test_deploy_basemirror` (own `trixie/13`, amd64, filter with the
    Depends of the `testproject-*` packages and the installer initrd packages; the system test mirror is not used,
    user decision) and `test_deploy_testproject` (`molior-validation/1` with `testproject`, waits for the build).
    In 1.4 the mirror and the build came from the tests before it (`after("test_build_notification")`, now
    `after("test_deploy_testproject")`).
  - The test: same metadata, parameters and arguments; the script path is absolute and the cwd is `RESULTS_DIR`
    (the deployments and their logs are uploaded); stdin is `/dev/null` (the cleanup question of molior-deploy gets
    the default).
  - `test-deploy.sh` (changed from 1.4, user decision): `molior-deploy -L` keeps the log of every deployment, and the
    deployment file is kept (1.4: `rm -f $IMG_FILE`); CI uploads both as the artifact `deployments`.
  - `test_molior_deploy` (changed from 1.4, user decision): for installer and vbox the deployment boots in VirtualBox
    (`utils.boot_vm`: the OVA imported, the ISO in a new VM with an empty 8 GB disk; headless, own `VBOX_USER_HOME`),
    a screenshot after `BOOT_WAIT` seconds (default 60) and the VM log go next to the deployment
    (`<deployment>.png`, `<deployment>.VBox.log`); the test fails if the VM does not start or does not run any more.
    No login check. The 1.4 test only checked that the file exists.
  - molior-tools `v1.5.0-alpha9` (newest tag on GitHub; the GitHub "latest release" is `v1.4.1`), built on the runner
    with `dpkg-buildpackage` (no release packages exist). molior-deploy downloads `/debootstrap/<base>_<version>_<arch>.tar.xz`
    from molior (1.4: nginx `location /debootstrap`); 1.5: FastAPI, `mount_static_files()` in `molior/fastapi/app.py`.
  - `test-deploy.sh` expects `<project>_<version>_3.0.12<suffix>`: the version of `testproject` (debian/changelog) is
    fixed in the script, as in 1.4 (there 3.0.11). 3.0.12 sets `INSTALL_PACKAGE` in the deploy files: molior-tools
    1.5 has no default for it any more.
