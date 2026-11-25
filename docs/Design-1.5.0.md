# Molior 1.5.0 — Design Document

## Table of Contents

1. [Purpose](#1-purpose)
2. [Concepts](#2-concepts)
3. [Roles and access](#3-roles-and-access)
4. [Mirroring](#4-mirroring)
   - [4.1 Why mirrors](#41-why-mirrors)
   - [4.2 Kinds of mirrors](#42-kinds-of-mirrors)
   - [4.3 Creating a mirror](#43-creating-a-mirror)
   - [4.4 Build environments](#44-build-environments)
   - [4.5 A new upstream state](#45-a-new-upstream-state)
5. [Projects and Versions](#5-projects-and-versions)
   - [5.1 Projects](#51-projects)
   - [5.2 Project versions](#52-project-versions)
   - [5.3 Dependencies](#53-dependencies)
   - [5.4 Dependency policy and binary compatibility](#54-dependency-policy-and-binary-compatibility)
   - [5.5 Release lifecycle of a version](#55-release-lifecycle-of-a-version)
6. [Building](#6-building)
   - [6.1 Source repositories](#61-source-repositories)
   - [6.2 What a repository declares](#62-what-a-repository-declares)
   - [6.3 Release builds and CI builds](#63-release-builds-and-ci-builds)
   - [6.4 What happens when a build runs](#64-what-happens-when-a-build-runs)
   - [6.5 Build order](#65-build-order)
   - [6.6 Following, retrying and aborting builds](#66-following-retrying-and-aborting-builds)
   - [6.7 Retention](#67-retention)
7. [Product deployments](#7-product-deployments)
8. [Architecture](#8-architecture)
   - [8.1 Components](#81-components)
   - [8.2 Queues and workers](#82-queues-and-workers)
   - [8.3 Build backend](#83-build-backend)
   - [8.4 Restarts](#84-restarts)
9. [Relationship with aptly](#9-relationship-with-aptly)
10. [Interfaces](#10-interfaces)
11. [Deploying molior](#11-deploying-molior)
    - [11.1 Common design](#111-common-design)
    - [11.2 Local development setup](#112-local-development-setup)
    - [11.3 Production deployment](#113-production-deployment)
    - [11.4 Upgrades and data](#114-upgrades-and-data)
12. [Software testing](#12-software-testing)
    - [12.1 Test levels](#121-test-levels)
    - [12.2 System test environment](#122-system-test-environment)
    - [12.3 System test layers](#123-system-test-layers)
    - [12.4 Rules for tests](#124-rules-for-tests)
    - [12.5 Validation tests from molior 1.4](#125-validation-tests-from-molior-14)
13. [Authentication](#13-authentication)
    - [13.1 Who logs in, and how](#131-who-logs-in-and-how)
    - [13.2 Sessions](#132-sessions)
    - [13.3 Live updates](#133-live-updates)
    - [13.4 Tokens](#134-tokens)
    - [13.5 Limits](#135-limits)
- [Appendix A: API endpoints](#appendix-a-api-endpoints)

---

## 1. Purpose

Molior is a **Debian build system**. It turns git repositories containing Debian packaging into signed APT repositories, for several distributions and architectures, in a repeatable way.

The problems it solves:

- **Repeatable builds on a fixed distribution.** A product is built against a frozen snapshot of a Debian distribution, not against a moving upstream archive. The same source built for the same release gets the same build environment and the same dependencies, even years later. (This is not "reproducible builds" in the Debian sense, which means bit-identical binary output.)
- **Products made of many packages.** A product consists of many git repositories, their build order, and third party repositories. Molior keeps them together as one project version and builds them in the right order.
- **Release and development side by side.** Every commit can be built and tested (CI) without touching what has been released.
- **Several architectures.** The same sources are built for amd64, i386, arm64 and armhf.
- **Releases that stay available.** A released version can be locked or snapshotted and stays installable as long as it is kept.

Molior is used through the **web UI**, the **REST API** and **command line tools**. It is built on [aptly](https://www.aptly.info/) for repository management and on sbuild for building packages in clean build environments.

Who uses it:

| User | Typical work |
|---|---|
| Developer | adds repositories, pushes commits and tags, follows builds and logs, installs CI packages for testing |
| Project owner / release manager | creates project versions, manages dependencies and permissions, locks, snapshots and copies versions for releases |
| Administrator | creates mirrors and projects, manages users, sets retention and maintenance |
| Automation (CI, molior-tools) | triggers builds and creates projects with tokens |

---

## 2. Concepts

```
 Mirrors                                   Projects
 ├── base mirror    "bookworm 12.11"       ├── project "myproduct"
 │     └── build environment per arch      │     ├── version "2.0"  ── based on one base mirror
 └── repo mirror    "kubernetes 1.32.6"    │     │     ├── depends on repo mirrors and other versions
       (belongs to a base mirror)          │     │     ├── contains source repositories (git)
                                           │     │     └── publishes: release channel + CI channel
                                           │     └── version "2.0-hotfix" (overlay)
                                           └── permissions, tokens
```

| Concept | Meaning |
|---|---|
| **Mirror** | A frozen copy of an external APT repository, made with aptly and served by molior. |
| **Base mirror** | A mirror of a distribution (e.g. Debian bookworm 12.11). It provides the build environment for each architecture. |
| **Repo mirror** | A mirror of an additional repository (e.g. Kubernetes, NVIDIA, security updates) for one base mirror. |
| **Project** | A product or team. It groups versions and carries permissions and tokens. |
| **Project version** | A release line of a project, built on one base mirror for a chosen set of architectures. It is an APT repository of its own. |
| **Dependency** | A repo mirror or another project version whose packages a version uses when building and installing. |
| **Source repository** | A git repository with Debian packaging. It can belong to many project versions. |
| **Build** | Building one git state: one source package, and binary packages for each project version and architecture. |
| **Release channel** | The `stable` distribution of a version, containing packages built from release tags. |
| **CI channel** | The `unstable` distribution of a version, containing packages built from untagged commits. |
| **Build environment** | A clean, minimal system of the base mirror for one architecture, in which packages are built. |

---

## 3. Roles and access

Access is granted per project. Every logged-in user can see all projects, mirrors and builds. The APT repositories and their sources lists are public, so that systems can install packages without logging in.

| Role | Scope | May |
|---|---|---|
| **Administrator** | system | everything: mirrors, projects, users, retention, cleanup, maintenance mode, rebuilding build environments |
| **Owner** | project | manage the project's versions (create, edit, copy, overlay, snapshot, lock, delete), dependencies, permissions and project tokens |
| **Member** | project | add and edit source repositories in the project's versions, trigger and retry builds |
| **Manager** | project | a role between member and owner. *To be defined; not used for any permission today.* |

**Tokens** are for automation, not for people:

- A **project token** acts on one project, for example a CI system that triggers builds after a push.
- A **global token** may create projects and mirrors, for example molior-tools setting up a new product.

**Maintenance mode** lets an administrator stop new work (for example before an upgrade). Non-administrators see a maintenance notice instead of the UI.

How people, tools and build jobs prove who they are is described in [13](#13-authentication).

---

## 4. Mirroring

### 4.1 Why mirrors

Building against the public Debian archive is not repeatable: it changes every day. Molior therefore builds only against **mirrors**: copies of external repositories taken at one point in time, verified with the upstream signing keys, and published again under molior's own signing key.

A mirror never changes after it has been created. This makes every build and every installation that uses it repeatable.

### 4.2 Kinds of mirrors

- **Base mirror.** A distribution, e.g. *bookworm 12.11*. Every project version is based on exactly one base mirror. It defines the distribution and the available architectures, and provides the build environments.
- **Repo mirror.** An additional repository that a product needs, e.g. Kubernetes packages or vendor drivers. It always belongs to one base mirror, because its packages are built for that distribution. Project versions can depend on it.
- **External repository.** A repository that is referenced but not copied. It is used where a full copy is not wanted. Builds that use it are not repeatable in the way they are with a real mirror.

### 4.3 Creating a mirror

Creating mirrors is an administrator task. The administrator gives:

- a name and version (e.g. *trixie* / *13.8*);
- the upstream URL, distribution, components and architectures;
- the upstream signing key (key URL or key server and key ids);
- optionally a package filter, and whether to include source packages and the installer;
- for a repo mirror, the base mirror it belongs to;
- the dependency policy (see [5.4](#54-dependency-policy-and-binary-compatibility)).

Then molior:

1. **creates** the mirror and imports the upstream keys,
2. **downloads** the packages and verifies them. The progress is shown live. A full distribution can be hundreds of GB and take hours,
3. **freezes** the downloaded state,
4. **publishes** it under molior's signing key,
5. for a base mirror, **prepares the build environments** (see 4.4),
6. marks the mirror **ready** and locks it.

If a step fails, the mirror shows an error and the administrator can retry it. A download that has been made is kept, so a retry does not start from zero. A retry of the mirror build retries only what failed: the failed build environments if the mirror itself is published, otherwise the mirror update.

Mirroring continues when molior is restarted: the download runs in the repository server, and molior picks up the progress again after its start.

A mirror that is still used by project versions cannot be deleted.

### 4.4 Build environments

For every architecture of a base mirror, molior creates a **build environment**: a minimal system of that distribution, installed from the mirror itself. Packages are always built in a fresh copy of it, so no build can influence another one.

**Change from 1.4:** a build environment is no longer a schroot tarball on the build host, but a **container image** per base mirror and architecture (for example `molior/trixie-amd64:13`). Molior creates it from the mirror (debootstrap, build tools, build user and build script), and pushes it to the container registry of the build backend. Build nodes pull it from there (see [8.3](#83-build-backend)), so no build environment has to be installed on a build host.

The build environments are created automatically when a base mirror is ready. Building for foreign architectures (arm on an amd64 host) uses emulation. An administrator can rebuild the build environments of a base mirror, for example after the build tooling has changed.

A project version can only build once the build environment for its base mirror and architecture exists.

### 4.5 A new upstream state

Because a mirror is frozen, a new upstream state (a Debian point release, new security fixes) is a **new mirror version**, e.g. *trixie 13.9* next to *trixie 13.8*. Existing project versions keep building on the old one. A project moves to the new base mirror by **copying** its version onto it (see [5.5](#55-release-lifecycle-of-a-version)), which rebuilds its packages on the new base.

---

## 5. Projects and Versions

### 5.1 Projects

A **project** stands for a product or a team. It groups the project's versions and carries the permissions (who is owner, manager or member) and the project tokens. Administrators create projects; owners manage them.

### 5.2 Project versions

A **project version** is a release line of a project, e.g. *myproduct / 2.0*. It is:

- **based on one base mirror**, which fixes the distribution and the build environment;
- built for a **set of architectures**, chosen from those of the base mirror;
- a set of **source repositories** that are built for it;
- a list of **dependencies** (repo mirrors and other project versions);
- an **APT repository** with two channels: *release* (stable) and *CI* (unstable).

A version can also be created **on top of another project version** (base project). It then inherits that version's base mirror and depends on it.

Each version has its own settings: whether CI builds are allowed, its dependency policy, and its retention (how many builds to keep).

### 5.3 Dependencies

A version can use packages from:

- **repo mirrors** of its base mirror (third party packages),
- **other project versions** (shared libraries, platform layers, other products).

Dependencies are followed transitively: if A depends on B and B on C, builds of A see C as well. When a version is built or installed, the APT sources are the base mirror, the version itself, and all its dependencies. Molior provides this sources list for every version, for builds and for installing target systems.

Molior refuses circular dependencies, and refuses dependencies that break the dependency policy.

For CI builds, a dependency can be marked to also use its **CI channel**, so that unreleased changes in a library can be tested together with the product that uses it.

### 5.4 Dependency policy and binary compatibility

Binary packages are only compatible with the system they were built on. A library built with an old compiler or against old libraries must not be used on a base whose compiler and libraries have changed, for example by a security fix. Mixing them can break at runtime in ways that are hard to find.

The **dependency policy** of a version (or a mirror) states who may depend on it:

| Policy | Who may use it as a dependency | Use |
|---|---|---|
| **strict** | only versions on the **same base mirror** | the default; guarantees binary compatibility |
| **distribution** | versions on **any base mirror of the same distribution** (e.g. any bookworm point release) | packages known to be compatible across point releases |
| **any** | every version | architecture independent content (data, scripts, documentation) |

To use a strict dependency on a newer base mirror, the dependency itself is copied onto that base mirror and rebuilt.

### 5.5 Release lifecycle of a version

```
create ──► develop (CI + release builds) ──► lock  or  snapshot ──► (copy for the next release)
                         │                                │
                         └──► overlay  (hotfixes on top of a released version)
```

| Step | Who | What it means |
|---|---|---|
| **Create** | owner | a new version on a base mirror (or on top of another version) |
| **Develop** | members | repositories are added, every commit and tag is built |
| **Lock** | owner | the version is frozen: no new builds, repositories or dependencies, and no CI builds. Only possible when all its dependencies are locked as well, so the release can be rebuilt completely from frozen inputs. A version can be unlocked again |
| **Snapshot** | owner | a new, locked version containing the latest successful build of every repository. The original version continues to be developed. The usual way to cut a release |
| **Copy** | owner | a new version with the same repositories and dependencies, optionally on another base mirror or with other architectures, optionally rebuilding the latest releases. Used for the next release line and for moving to a new base mirror |
| **Overlay** | owner | a new version on top of a (released) version that depends on it. Used for **hotfixes**: only the fixed packages are built into the overlay; everything else comes from the released version, which stays untouched |
| **Delete** | owner | removes a version that is not locked and has no running builds |

An owner can also **retry all failed builds** of a version, or **abort** its running builds.

---

## 6. Building

### 6.1 Source repositories

A source repository is a git repository that contains Debian packaging (`debian/`). Members add it to a project version by its URL, and choose the architectures it is built for in that version. The same repository can be part of many versions and projects. Molior clones it once.

Molior needs read access to the repositories; the SSH key it uses is shown on the About page.

When a repository is added, molior builds its **latest release tag** right away.

### 6.2 What a repository declares

Some information belongs to the source code, not to molior. A repository declares, in `debian/molior.yml`:

- **targets**: the project versions it is meant for. A tag is built for the versions that are listed there **and** contain the repository. This way a release tag of a library can go to several products at once, and a repository cannot be built into a version by accident;
- **build after**: other repositories that must be built before it (see [6.5](#65-build-order)).

The package version comes from `debian/changelog`, as usual for Debian packages.

### 6.3 Release builds and CI builds

Molior distinguishes two kinds of builds, decided by the git state:

| | Release build | CI build |
|---|---|---|
| Trigger | a **git tag** that matches the version in `debian/changelog` (e.g. tag `v1.2.3` for version `1.2.3`) | any other commit, e.g. a push to a branch |
| Version | the changelog version | the changelog version plus date and commit, so it is always newer and always unique |
| Published to | **release channel** (stable) | **CI channel** (unstable) |
| Uses | released dependencies | released dependencies, plus CI channels where configured |
| Allowed | always (unless the version is locked) | only if CI builds are enabled for the system and the version |
| Kept | according to retention | automatically removed after some days |
| Lintian checks | if enabled for the repository | no |

This lets developers test every change as an installable package without affecting the release channel that target systems install from.

Rules that protect releases:

- The same version is built only once. A second trigger for an already built version reuses the existing result.
- A version lower than one already released in the same project version is refused.
- Locked versions receive no builds.

Builds are triggered:

- by adding a repository to a version (latest release tag),
- by "build latest" on a repository,
- by a git hook or CI system through the API, for a branch, commit or tag,
- by copying a version with "rebuild latest releases",
- by uploading prebuilt packages to a version (external build).

### 6.4 What happens when a build runs

One trigger results in one **build tree**:

```
build        "mylib 1.2.3"                       ← what the user triggered
└── source   source package mylib 1.2.3          ← built once
    ├── binary  myproduct/2.0     amd64
    ├── binary  myproduct/2.0     arm64
    └── binary  otherproduct/1.4  amd64          ← one per target version and architecture
```

1. **Prepare.** The git state is checked out, the version and the targets are determined, and the build tree is created.
2. **Source package.** The Debian source package is built once and published to the target versions.
3. **Binary packages.** For each target version and architecture, a binary build is queued. It starts when the build environment is ready, a build slot for the architecture is free, and its build order allows it (6.5).
4. **Build.** The build runs in a fresh build environment that only sees the base mirror, the version and its dependencies. The log is streamed live to the user.
5. **Publish.** The resulting packages are added to the version's channel, and the APT repository is published again. Installing systems see the new packages immediately, and never a half-updated repository.
6. **Done.** When all binary builds are published, the whole build is successful.

The states a user sees:

```
new → queued → scheduled → building → publishing → successful
                              │            │
                         build failed   publish failed
```

A build that had nothing to do ends as *already exists* (built before), *already failed*, or *nothing done* (no matching target, or CI not allowed).

### 6.5 Build order

When packages of a product depend on each other, a package must be built after the packages it needs. A repository lists them under *build after*, by **repository name** (the last part of its git URL, without `.git`), not by package name. Molior looks for them in the version and its dependencies, and holds the binary build back while any of them is still being built or published in those versions. Independent packages build in parallel.

An entry that matches no repository in the version or its dependencies is an error: the build is not started and waits, and its log says which dependency is missing. The scheduler checks waiting builds again whenever builds finish, so it can start after a repository of that name is added and a build of it is published.

### 6.6 Following, retrying and aborting builds

- The **build list** shows all builds as trees, filterable by project, version, repository, maintainer, commit and state. It updates live.
- The **build page** shows the live log of a build and of its parts.
- A failed build can be **retried**. Its log is kept with the build.
- Running builds can be **aborted**, per build or for a whole version.
- Builds can be **deleted**, which also removes their packages from the repository.
- **Build notification hooks are dropped in 1.5.** In molior 1.4 a web hook could be set per source repository (URL,
  method, body), which molior called when a build of that repository changed its state. 1.5 has no such hooks: builds
  are followed in the web UI with live updates, and other systems use the REST API (see [10](#10-interfaces)).

### 6.7 Retention

Every publish would otherwise make repositories grow without end. Each version therefore keeps:

- a fixed **number of successful builds per repository**. Older ones are removed together with their packages;
- **failed builds** for a number of days.

The defaults are set by the administrator and can be changed per version. A regular **cleanup** applies the rules to all versions that are not locked. Locked versions and snapshots are never cleaned up. CI packages expire after a few days.

---

## 7. Product deployments

*To be written.*

Building packages is one half; the other half is turning a project version into something that can be installed: ISO installers, VM images, containers. This is done by **molior-tools** and **molior-deploy**, which use the APT sources of a project version. This chapter will describe:

- how a deployment is defined for a project version,
- how molior-tools and molior-deploy create it from the version's repositories,
- how deployments relate to release and CI channels, and to locked versions and snapshots.

---

## 8. Architecture

This chapter shows how the workflows above are implemented, at the level of components. The implementation details follow in separate documents.

### 8.1 Components

```
        Web UI (browser)          CLI, CI systems, molior-tools
                 │   REST API, live updates   │
┌────────────────▼────────────────────────────▼───────────────┐
│ molior server                                               │
│   API · live updates · task worker · aptly worker ·         │
│   build backend · source package builds                     │
│ database (all metadata: mirrors, projects, builds, users)   │
└───────┬─────────────────────────────────┬───────────────────┘
        │ repository operations           │ build jobs
┌───────▼──────────────────────┐   ┌──────▼──────────────────────────┐
│ repository server (aptly)    │   │ build jobs (one per binary      │
│   mirrors, repositories,     │   │ build, per architecture) on     │
│   snapshots, publishing      │◄──│ Kubernetes nodes, using build   │
│ web server for the APT repos │   │ environment images              │
└──────────────────────────────┘   └─────────────────────────────────┘
```

| Component | Responsibility |
|---|---|
| **molior server** | API, permissions, the state of everything, and coordinating the work |
| **database** | mirrors, projects, versions, repositories, builds, users, settings |
| **repository server (aptly)** | stores and publishes all packages; downloads mirrors |
| **APT web server** | serves the published repositories to builds and target systems |
| **build jobs** | build binary packages in isolated, short-lived containers |
| **image registry** | holds the build environment images |

### 8.2 Queues and workers

Work is done in the background, in queues, so that the API stays responsive:

- **Task worker**: git operations, preparing builds, source packages, scheduling binary builds, and creating build environments.
- **aptly worker**: every change to repositories (mirrors, creating and deleting versions, publishing builds, snapshots, cleanup). It works **one task at a time**, so that repositories are always changed in a defined order and never by two operations at once.
- **Build queue**: binary builds wait here per architecture until a build slot is free.
- **Notifications**: every change is sent to the connected web UIs as a live update.

Long running work (a mirror download, a binary build) runs alongside the queues and reports its progress. The number of parallel binary builds per architecture, parallel source package builds, and parallel build environment creations are limited by configuration.

### 8.3 Build backend

Binary builds run as **Kubernetes jobs**. Each job:

- uses the build environment image of its base mirror and architecture,
- runs on a node of the matching architecture,
- gets the APT sources of its project version from molior,
- builds the package, uploads the results to molior, and streams its log,
- is removed afterwards.

Source packages are built by the molior server itself, as they are architecture independent.

### 8.4 Restarts

The repository server runs independently of the molior server. When molior restarts:

- **mirrors** that are downloading continue in the repository server, and molior resumes tracking them;
- **builds waiting to be published** are published;
- **queued builds** are queued again;
- **builds that were running** are marked failed and can be retried.

---

## 9. Relationship with aptly

Molior keeps the **knowledge** (what belongs to what, who may do what, which build produced which package). aptly keeps the **packages** and publishes them. Molior never changes package files itself; it asks aptly to do it.

| Molior concept | aptly |
|---|---|
| mirror | an aptly mirror per component, frozen as a snapshot, published |
| project version | two aptly repositories (release and CI channel), each published from a snapshot |
| publishing a build | add the packages to the repository, create a new snapshot, switch the published repository to it at once |
| version snapshot | an aptly snapshot of the selected packages, published as a new version |
| retention, deleting builds | remove packages from the repository, then publish again |

Publishing by switching snapshots means that a target system always sees either the old or the new state of a repository, never a mix.

All repositories are published under one tree, which reflects the concepts:

```
<base mirror>/<version>                                         the distribution
<base mirror>/<version>/mirrors/<repo mirror>/<version>         its repo mirrors
<base mirror>/<version>/repos/<project>/<version>               project versions (stable, unstable)
```

Everything is signed with molior's repository key; the public key is shown on the About page.

---

## 10. Interfaces

- **Web UI**: all user workflows, with live updates of builds, logs and mirror progress.
- **REST API**: everything the UI can do, for scripts and integrations. Documented with OpenAPI; the endpoints are listed in [Appendix A](#appendix-a-api-endpoints).
- **Tokens**: for CI systems and molior-tools (see [3](#3-roles-and-access)).
- **APT sources**: a ready-to-use sources list for every project version and mirror, public.
- **Build interface**: build jobs fetch their sources list and upload their results with a one-time token per build.
- **Not in 1.5**: build notification hooks (calls to other systems when a build changes its state, see [6.6](#66-following-retrying-and-aborting-builds)).

---

## 11. Deploying molior

### 11.1 Common design

Molior is deployed on **Kubernetes** with **one Helm chart** for all environments. Each environment only has its own settings file: host names, registry, storage sizes, number of build slots, signing key identities. Secrets (passwords) are kept in a Kubernetes secret and never in the settings.

```
┌──────────────────────────── Kubernetes cluster ─────────────────────────────┐
│                                                                             │
│  molior pod                        aptly pod                                │
│  ┌──────────────────────┐          ┌───────────────────────────┐            │
│  │ molior server        │──────────│ repository server (aptly) │            │
│  │ database (postgres)  │          │ APT web server (nginx)    │            │
│  └───┬──────────────┬───┘          └─────────────┬─────────────┘            │
│      │ volume:      │ volume:                    │ volume:                  │
│      │ git clones,  │ database                   │ package pool,            │
│      │ build logs   │                            │ published repositories   │
│      │                                                                      │
│      │ creates                                                              │
│      ▼                                                                      │
│  build jobs (amd64 nodes)   build jobs (arm64 nodes)                        │
└──────┬──────────────────────────────────────────────────────────────────────┘
       │ pull / push build environment images
┌──────▼───────────┐
│ image registry   │   molior images and build environment images
└──────────────────┘
```

| Part | Design decision |
|---|---|
| **molior pod** | molior server and its database run together; the database is only used by molior |
| **aptly pod** | separate, so it keeps running (and mirroring) while molior is upgraded or restarted |
| **storage** | three persistent volumes: molior data, database, repositories. They are kept when the chart is removed, so a reinstall never loses data |
| **build jobs** | created on demand by molior through the Kubernetes API, one per binary build, on nodes of the right architecture; molior only has the permissions needed for this |
| **image registry** | holds the molior images and the build environment images, which molior creates itself for each base mirror and architecture |
| **signing keys** | repository and package signing keys live on the volumes, not in images |
| **database schema** | upgraded automatically when the molior server starts |

### 11.2 Local development setup

For development, molior runs on a **local Kubernetes cluster in containers (k3d)** on the developer's machine:

- the cluster and a **local image registry** run as containers;
- molior images are **built from the working copy** and pushed to the local registry, so a code change is tested by building the images and restarting the molior pod;
- the same chart is used as in production, with a **development flag** that allows plain HTTP (no TLS) and test passwords;
- volumes are small and live inside the cluster, and can be thrown away;
- builds run on the developer's machine; amd64 builds natively, arm builds through emulation (see below);
- a copy of production data (database and repositories) can be imported for realistic tests.

The goal is that what works locally works in production: same images, same chart, same build backend. Only scale and access differ.

**Arm builds without arm nodes (testing only).** For testing, arm64 and armhf packages can be built on amd64 nodes through emulation (qemu): install `binfmt-support` and `qemu-user-static` on the hosts of the amd64 nodes (the qemu handlers must be registered so that they also work inside chroots and containers, see the development notes), and set the node label of the arm builders to the amd64 label in the environment's settings. The arm build jobs then run on the amd64 nodes, and the arm programs in them run emulated. This is **not recommended for production**: emulated builds are a lot slower, and emulation can behave differently from real arm hardware. Production uses real arm nodes (see [11.3](#113-production-deployment)).

### 11.3 Production deployment

In production, molior runs on a **regular Kubernetes cluster (kubeadm)**:

- **Front end on the host:** a web server on the host terminates **TLS** and forwards to molior's web UI and API. The APT repositories are served to builds and target systems through their own entry point.
- **Image registry on the host**, also behind TLS; the cluster nodes trust its certificate. Pushing images needs a password, pulling does not.
- **Storage:** the three volumes are bound to fixed directories on the host's data disk, so data stays where it is across reinstalls and can be backed up with the host.
- **Build nodes:** amd64 builds run on the cluster's amd64 nodes, arm builds on arm64 nodes. Building arm on amd64 nodes through emulation is for testing only (see [11.2](#112-local-development-setup)). The number of parallel builds per architecture is set per environment.
- **Signing keys** of the existing installation are kept, so target systems keep trusting the repositories.
- **Name resolution:** pods must resolve the registry host name, also when the host has no DNS entry.

Network access needed: from the cluster to the upstream mirrors (downloads), to the git servers (clones, read access with molior's SSH key), and from target systems to the APT repositories.

### 11.4 Upgrades and data

- **Code upgrade:** new images are built and pushed to the registry, then the molior pod is restarted. The aptly pod is not restarted, so mirror downloads continue (see [8.4](#84-restarts)). Running builds are lost and can be retried, so upgrades are done when the build queue is idle.
- **Configuration change:** the chart is reinstalled. The volumes are kept.
- **Database upgrade:** applied automatically by the new molior version at start.
- **Data import or restore:** molior can be held back at start, so that only the database runs; the data is imported, and molior is released.
- **Maintenance mode** is used to stop new work before an upgrade (see [3](#3-roles-and-access)).

---

## 12. Software testing

### 12.1 Test levels

| Level | Tests | Runs against |
|---|---|---|
| **Unit tests** | single modules and functions: state changes, error handling, retries | test doubles instead of the database, aptly and Kubernetes; no deployment needed |
| **System tests** | molior as a whole, through its interfaces: REST API, web UI, APT repositories | a complete molior deployment, built from the working copy |

Unit tests are fast and show exactly which function is wrong, but they cannot find errors between the parts: an API that reads a different header than the clients send, or a database query that only fails on a real database. System tests find these. Both levels are kept separate and are run separately.

### 12.2 System test environment

Each system test run creates its **own throwaway environment** and removes it afterwards:

```
┌──────────────────── test host (developer machine or CI runner) ─────────────────────┐
│                                                                                     │
│  test registry (per run)          k3d cluster (per run)                             │
│  ┌──────────────────────┐         ┌──────────────────────────────────────────────┐  │
│  │ molior images, built │────────►│ molior pod      aptly pod                    │  │
│  │ from the working copy│         │      ▲              ▲                        │  │
│  │ test runner image    │         │      │ REST API, web UI, APT repositories    │  │
│  └──────────────────────┘         │ test runner pod: tests, headless browser     │  │
│                                   └──────────────────────────────────────────────┘  │
│  results: test report, screenshots, server logs, server code coverage               │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

| Part | Design decision |
|---|---|
| **cluster per run** | a new k3d cluster with its own image registry for every run. Runs never share state, several runs can run side by side, and the developer's own cluster and settings are not touched |
| **same chart** | molior is installed with the production Helm chart (see [11](#11-deploying-molior)) and a test settings file. The images have their normal names, in the test registry |
| **images from the working copy** | the molior images are built from the working copy, so the tests check the code as it is. The molior image used for tests additionally measures which server code the tests run (code coverage) |
| **tests inside the cluster** | the tests run in a separate test runner pod, with the test tools and a headless browser. They reach molior through its cluster services, the way other clients do; no ports are opened on the host. The molior images contain no test tools |
| **random passwords** | admin and aptly passwords are generated per run |
| **results** | the test report (JUnit XML), screenshots of failed web UI tests, the logs of the molior server, database and aptly, and the server code coverage are copied out before the cluster is removed |
| **nothing left behind** | the cluster, the registry and their volumes are removed after every run, also after a failure or an interrupt. Leftovers of runs that were killed are removed by the next run. For debugging, a run can keep its cluster on request |
| **same for CI** | one script does all of this, and the same script runs on a developer machine and in CI. It needs docker, k3d, Helm and kubectl on the host |

### 12.3 System test layers

The system tests are built up in layers. Each layer needs more of the environment and takes longer:

| Layer | Tests | Needs | State |
|---|---|---|---|
| **Smoke** | login and logout, permissions, users, projects, tokens, error responses, every page of the web UI renders | molior only, no mirror, no builds | done |
| **Mirror** | creating a small base mirror, build environments, project versions, dependencies, copy | a small filtered upstream mirror and the build environment images | planned |
| **Build** | release and CI builds from a git repository, publishing, the APT repositories, retention, retrying, a restart during a build; the validation tests from molior 1.4 (see [12.5](#125-validation-tests-from-molior-14)) | the test packages (see [12.5](#125-validation-tests-from-molior-14)) | planned |
| **CI** | the system tests run for every change | docker and k3d on the CI runners | planned |

### 12.4 Rules for tests

- **Public interfaces only:** system tests use what clients use (REST API, web UI, APT repositories). They do not read or change the database or aptly directly.
- **Existing clients:** API behaviour that existing clients rely on is tested as the clients use it, so that a change that breaks them fails a test. Example: token authentication with the header that molior-tools and CI systems send.
- **Independent tests:** each test creates its own data with unique names, so the tests do not depend on each other or on their order.
- **A failing test is a bug:** a test that finds a bug stays failing until the bug is fixed; it is not changed to match the wrong behaviour.

### 12.5 Validation tests from molior 1.4

Molior 1.4 was validated with a set of system tests against an installed molior. Their test cases are linked to user requirements (package building, CI builds, build order, parallel builds, short tests during the build, build logs, mirrors, project versions, dependencies, role based access) and were the basis of the 1.4 validation report.

These tests are taken over into the 1.5 system tests, so that 1.5 is checked against the same requirements:

| Aspect | Design decision |
|---|---|
| **Traceability** | each taken over test keeps its name, description, test id and requirement references, so the link to the requirements and to the 1.4 report stays |
| **Same steps, current interfaces** | the steps and checks stay the same. They are written in the same way as the other system tests, instead of the REST test tool used in 1.4, and use the 1.5 interfaces where the old ones are gone: mirrors are created with the current API, users are local instead of LDAP, and what 1.4 checked by SSH on the hosts is checked in the containers of the test installation (build logs, the aptly service and its storage). The build environment test pulls the build environment image from the registry, as a build node does, instead of looking for the schroot tarball (see [4.4](#44-build-environments)) |
| **Current distribution** | the tests run on a Debian trixie base mirror instead of stretch |
| **Only what applies** | tests of functionality that molior 1.5 no longer has are not taken over, instead of being copied and disabled: build notification hooks, and the cleanup of a long-lived test installation (every test run gets a new one). Product deployments are tested with the deployment tools (see [7](#7-product-deployments)) |
| **Third party mirrors** | tests that mirrored third party software use current public repositories of the same software instead of the old internal copies, with a filter so that only what the test builds with is mirrored |
| **Later** | the arm build tests are taken over when the test environment can build arm packages |

The tests build a set of small **test packages**, each covering one case: a successful build with a passing short test, a build failing in its short test, build order between packages, several binary packages from one source, a package without molior configuration (never built), CI builds, one source for two project versions, files stored with git LFS, git submodules, and an architecture dependent package for arm. They come from the 1.4 tests and were cleaned up and updated for trixie. They are kept as public git repositories (one per package, named `test-<name>`) in the molior organisation on GitHub, from where the system tests build them. Build order entries therefore use these repository names.

The parallel build test adds all test packages to one version at once and waits until all of them have ended, successful or failed as expected. A package whose build order dependency is not found never ends, so this test fails then. That the build order was kept (a package starts only after the package it needs has ended) is checked by the build order test, from the start and end times of the builds.

---

## 13. Authentication

Chapter [3](#3-roles-and-access) says *what* a caller may do. This chapter says how molior knows *who* the caller is, for the REST API, the live updates and the build jobs.

### 13.1 Who logs in, and how

| Caller | Proves its identity with | Checked against |
|---|---|---|
| **user** (web UI, scripts) | user name and password, then a session cookie | the user database (passwords stored as salted hashes); an authentication backend can be plugged in instead |
| **administrator account** `admin` | user name and password, then a session cookie | the password in molior's settings, not the user database |
| **CI system, molior-tools** | a token in the `X-MoliorToken` header of each request | the token list (only a hash of each token is stored) |
| **build job** | a token per build in the URL of the build interface (upload, log) | the build it belongs to |
| **anyone** | nothing | public endpoints only: status, APT sources, version and mirror details (see [Appendix A](#appendix-a-api-endpoints)) |

After the identity is known, the permissions of [3](#3-roles-and-access) apply: administrators may do everything, users what their project roles allow, tokens what they were created for.

### 13.2 Sessions

- A successful login creates a **session** on the server and returns a **session cookie**. The browser sends it with every request and with the live update connection, so the web UI needs no other credentials.
- The cookie holds a long random value. The server stores only a hash of it, with the user and the expiry, so the database does not contain values that log in. A cookie that is not in the session list does not log in.
- Each login is its own session: two browsers have two different cookies.
- A session is valid for **3.5 days** after the login (as in molior 1.4). After that, the API answers *401*, and the live update connection of the web UI is closed with a `401` message, on which the web UI shows the login page (see [13.3](#133-live-updates)).
- The cookie cannot be read by scripts in the page (HttpOnly), is not sent with requests started by other sites (SameSite=Lax), and is only sent over HTTPS in production.
- Every request checks the session and the user: an ended session or a deleted user is rejected at once.
- **The sessions of a user end** (all browsers), and their live update connections are closed, when:
  - the user **logs out** in any browser,
  - an administrator **changes the user's password**,
  - an administrator **deletes the user** (a user created later with the same name does not get the old sessions).
- Ending a session works on the server: a copy of the cookie does not work any more either.
- Expired sessions are removed from the session list at the next login.
- The upgrade to molior 1.5 with this session list ends the logins made before.

### 13.3 Live updates

The live update connection (`/api/websocket`, see [10](#10-interfaces)) needs a login, like the REST API, as in molior 1.4.

- When the connection opens, the server checks the session cookie or the token. Without a valid login it sends `{"status": 401}` and closes the connection. The web UI logs out on this message and shows the login page.
- While the connection is open, it is closed in the same way (`{"status": 401}`, then closed) when:
  - the **sessions of the user end** (see [13.2](#132-sessions)), at once,
  - its **session expires**, at the moment of expiry,
  - its session, its user or its token is gone for another reason. The server checks this every minute.
- After the `401` message the connection sends nothing else: no build or mirror updates, no build log.
- If the login cannot be checked for a moment (the database does not answer), the open connection stays. A connection that cannot be checked when it opens is closed without the `401`, so that the web UI does not log the user out because of a short outage.
- The Server-Sent Events channel (`/api/events`) needs a login as well; it checks it when it is opened.

### 13.4 Tokens

- **Project and global tokens** are for automation (see [3](#3-roles-and-access)). Molior shows a token **once**, when it is created; only a hash of it is stored. Tokens do not expire: a token is valid until an owner or administrator deletes it. Open live update connections of a deleted token are closed within a minute.
- **Build tokens** are created for each build. A build job uses its token to upload its results and stream its log (see [10](#10-interfaces)); the sources list and the source package it fetches are public. A build token gives access to its own build only, not to the API. The build job gets it in its environment, but the package build itself runs with a clean environment and does not see it.

### 13.5 Limits

- **One server process.** The open live update connections are found in the memory of the server process. Molior runs as one process. With several processes, the connections in the other processes would be closed at their next check, within a minute, instead of at once.
- **No list of sessions in the UI.** Users and administrators cannot see the sessions or end a single one; ending the sessions of a user ends all of them.
- **Password rules and login limits** (lockout after failed logins) are not part of 1.5.

---

## Appendix A: API endpoints

Endpoints are grouped by the chapters above. `/api` is the original API, `/api2` the newer one; both are in use. `{p}/{v}` stands for project and version. Access: *public* (no login), *user* (logged in), *member*, *owner* (of the project), *admin*.

### A.1 Session and users (chapters 3 and 13)

| Method | Path | Access | Purpose |
|---|---|---|---|
| POST | `/api/login` | public | log in |
| GET, POST | `/api/logout` | user | log out: end all sessions of the user, close their live update connections |
| GET | `/api/userinfo` | user | current user |
| GET, POST | `/api/users` | user, admin | list users, create a user |
| PUT, DELETE | `/api/users/{id}` | admin | edit, delete a user (a new password or deleting ends the user's sessions) |
| GET | `/api/users/{id}/roles` | admin | project roles of a user |
| GET | `/api/userroles` | public | list of roles |
| GET | `/api2/user/{username}` | user | user details |
| GET, POST, DELETE | `/api2/tokens` | user | global tokens |
| GET, POST, PUT, DELETE | `/api2/projectbase/{project}/permissions` | owner | project roles |
| GET, POST, PUT, DELETE | `/api2/projectbase/{project}/tokens`, `/token` | owner | project tokens |
| GET, PUT, DELETE | `/api/projects/{id}/users/{user}` | owner | project roles (original API) |

### A.2 Mirrors (chapter 4)

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/api/mirrors` | user | list mirrors |
| POST | `/api2/mirror` | admin | create a mirror |
| GET | `/api2/mirror/{name}/{version}` | public | mirror details |
| PUT | `/api2/mirror/{name}/{version}` | admin | edit a mirror that is not ready yet |
| DELETE | `/api2/mirror/{name}/{version}` | admin | delete an unused mirror |
| POST | `/api/mirror/{id}/update` | admin | retry a failed mirror |
| GET | `/api2/mirror/{name}/{version}/dependents` | user | versions using the mirror |
| GET | `/api2/mirror/{name}/{version}/aptsources` | public | APT sources of the mirror |

### A.3 Projects and versions (chapter 5)

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET, POST | `/api/projects` | user, admin | list projects, create a project |
| GET, PUT | `/api/projects/{id}` | user, owner | project details, edit |
| GET | `/api2/projectbase/{project}` | user | project details |
| DELETE | `/api2/projectbase/{project}` | owner | delete an empty project |
| GET | `/api2/projectbase/{project}/versions` | user | versions of a project |
| POST | `/api2/projectbase/{project}/versions` | owner | create a version |
| GET | `/api/projectversions` | user | list and search versions |
| GET | `/api2/project/{p}/{v}` | public | version details |
| PUT | `/api2/project/{p}/{v}` | owner | edit a version |
| DELETE | `/api2/project/{p}/{v}` | owner | delete a version |
| POST | `/api/projectversions/{id}/toggleci` | owner | allow or stop CI builds |
| GET | `/api2/project/{p}/{v}/dependencies` | user | dependencies, or candidates to add |
| POST | `/api2/project/{p}/{v}/dependencies` | owner | add a dependency |
| DELETE | `/api2/project/{p}/{v}/dependency` | owner | remove a dependency |
| GET | `/api2/project/{p}/{v}/dependents` | user | versions depending on it |
| POST | `/api2/project/{p}/{v}/lock`, `/unlock` | owner | lock, unlock |
| POST | `/api2/project/{p}/{v}/snapshot` | owner | snapshot into a new locked version |
| POST | `/api2/project/{p}/{v}/copy` | owner | copy into a new version |
| POST | `/api2/project/{p}/{v}/overlay` | owner | create a hotfix overlay |
| POST | `/api2/project/{p}/{v}/retry` | owner | retry all failed builds |
| POST | `/api2/project/{p}/{v}/abort` | owner | abort running builds |
| GET | `/api2/project/{p}/{v}/aptsources` | public | APT sources of the version and its dependencies |
| GET | `/api/projectsources/{p}/{v}` | public | APT sources (original API) |
| GET | `/api2/project/{p}/{v}/export` | public | export a version definition |
| POST | `/api2/projectbase/projectversion/import` | owner | import a version definition |
| POST | `/api2/project/{p}/{v}/s3` | owner | publish a version to an external S3 endpoint |
| GET | `/api2/s3` | user | available S3 endpoints |

### A.4 Source repositories and builds (chapter 6)

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/api2/project/{p}/{v}/repositories` | public | repositories of a version |
| POST | `/api2/project/{p}/{v}/repositories` | member | add a repository |
| GET, PUT, DELETE | `/api2/project/{p}/{v}/repository/{id}` | member | repository settings in a version, remove it |
| GET | `/api/repositories`, `/api2/repositories` | user | list repositories |
| GET | `/api2/repository/{id}` | user | repository details |
| GET | `/api2/repository/{id}/dependents` | user | versions containing it |
| PUT | `/api2/repository/{id}` | admin | change the git URL |
| PUT | `/api2/repository/{id}/merge` | admin | merge a duplicate repository |
| DELETE | `/api2/repository/{id}` | admin | delete an unused repository |
| POST | `/api/repositories/{id}/clone` | user | clone a failed repository again |
| POST | `/api/repositories/{id}/build` | user | build the latest release tag |
| POST | `/api/build` | user | trigger a build for a git ref (git hooks, CI) |
| POST | `/api2/project/{p}/{v}/extbuild` | owner | upload prebuilt packages |
| GET | `/api/builds` | user | list and filter builds |
| GET | `/api/build/{id}` | public | build tree |
| GET | `/api2/build/{id}` | user | build details |
| PUT | `/api2/build/{id}` | user (admin for mirror builds) | retry a build |
| POST | `/api2/build/{id}/abort` | user | abort a build |
| DELETE | `/api2/build/{id}` | user | delete a build and its packages |
| DELETE | `/api2/project/{p}/{v}/build/{id}` | owner | delete a build from a version |
| GET | `/api/buildstates` | user | list of build states |

### A.5 Administration (chapters 3 and 6.7)

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET, PUT | `/api2/retention` | admin | default retention |
| GET, PUT | `/api2/cleanup` | admin | cleanup schedule |
| GET, PUT | `/api2/maintenance` | admin | maintenance mode and message |
| GET | `/api/status` | public | versions, maintenance state, public keys |
| POST | `/api/status/maintenance` | admin | maintenance mode (original API) |
| GET | `/api/info/aptlyhostname` | user | host name of the APT repositories |

### A.6 Live updates and build interface (chapters 8, 10 and 13)

| Method | Path | Access | Purpose |
|---|---|---|---|
| WebSocket | `/api/websocket` | user | live updates of builds, logs and mirrors |
| GET | `/api/events` | user | the same as Server-Sent Events |
| POST | `/internal/buildupload/{token}` | build job | upload a build result |
| WebSocket | `/internal/buildlog/{token}` | build agent | stream a build log (node based agents) |
| GET | `/api2/docs`, `/api2/openapi.json` | public | OpenAPI documentation |
