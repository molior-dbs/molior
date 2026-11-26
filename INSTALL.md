# Development Setup

This guide covers running the full Molior stack locally using k3d (Kubernetes in Docker).

## Clone the repositories

The main development repositories (checked out side by side):

```sh
git clone https://github.com/molior-dbs/molior
git clone https://github.com/molior-dbs/molior-web2
```

The directory layout should be:
```
./molior/
./molior-web2/
```

All subsequent commands are run from inside the `molior/` directory.

The following related source repositories are part of the molior 1.5 project version
and will be built inside the cluster:

```sh
git clone https://github.com/molior-dbs/aiofile
git clone https://github.com/neolynx/launchy
git clone https://github.com/molior-dbs/molior-tools
```

---

## Prerequisites

- Linux host with `podman` or `docker` installed
- `kubectl` and `helm` available in `PATH`
- `k3d`, install it with:

```sh
make install-deps
```

> This downloads k3d (pinned version, checksum verified) to `~/.local/bin/k3d`. Make sure `~/.local/bin` is in your `PATH`.

`make help` lists the targets by workflow. The Local Development targets work on the local k3d cluster (kubectl
context `k3d-<cluster>`, the current context is not used).

---

## 1. Create the local cluster

Creates a local k3d registry and Kubernetes cluster with the required port mappings:

```sh
make create-cluster
```

This sets up:
- A local image registry at `k3d-molior-registry:5000`
- A k3d cluster named `molior`
- Port `8000` → Molior web UI
- Port `8080` → Aptly repository

Another name: `make create-cluster K3D_CLUSTER=local` creates the cluster `local` and the registry `k3d-local-registry:5000`.
Pass the same `K3D_CLUSTER` to all Local Development targets.

Other host ports, e.g. for a second cluster next to an existing one: `K3D_WEB_PORT` (default 8000), `K3D_APTLY_PORT`
(8080) and `K3D_REGISTRY_PORT` (5000, also the registry port inside the cluster). Pass them to all Local Development
targets too.

`make create-cluster` does not change the current kubectl context.

---

## 2. Build the Docker images

```sh
make docker-images
```

This builds `molior`, `molior-postgres`, `aptly` and `molior-nginx` (tag `dev`), and the base image `molior-base`
when it is missing.

---

## 3. Deploy the images

```sh
make deploy
```

Pushes the images into the k3d registry.

---

## 4. Install the Helm chart

```sh
make install-helmchart
```

Installs molior with the `charts/` Helm chart. `VALUES=<file>` adds a values file,
for example `make install-helmchart K3D_CLUSTER=local VALUES=values-local.yaml`.

The passwords are not chart values: they are read from the Secret `molior-passwords` (keys `molior-password`,
`aptly-password`, `registry-password`). `make install-helmchart` creates it with the dev password `molior-dev` if it
does not exist. `make set-passwords` changes them on the cluster of the current kubectl context: it asks for the
passwords (an empty answer keeps the current one).

---

## 5. Monitor the pods

`make list`, `make watch`, `make logs`, `make shell`, `make psql`, `make restart` and the other Molior Maintenance
targets use the current kubectl context. Switch to the new cluster first:

```sh
kubectl config use-context k3d-molior
make watch
```

Once all pods are running, Molior is available at **http://localhost:8000** and the Aptly repository at **http://localhost:8080**.

---

## Common workflows

### Rebuild molior and restart it (dev loop)

```sh
make reload
```

### Rebuild all images and install again

```sh
make redeploy
```

### Install the Helm chart again (no image rebuild, no push)

```sh
make uninstall-helmchart install-helmchart
```

### View logs

```sh
make logs               # molior + aptly (current context)
make logs APP=molior
make logs APP=aptly
```

### Restart, shell, database

```sh
make restart            # molior and aptly pods (current context)
make restart-molior     # molior pod (current context)
make restart-aptly      # aptly pod (current context)
make shell              # molior pod (current context), APP=aptly for aptly
make psql               # molior database (current context)
```

### Tests

```sh
make lint               # flake8 in the image molior-ci:dev (built if missing), no local flake8 needed
make unit-tests         # pytest in the same image, the source tree mounted
make system-tests       # all suites in a throwaway k3d cluster, or TEST=<pytest args>
```

---

## Teardown

```sh
make delete-cluster
```

This deletes the k3d cluster with its data (database, repositories). The registry `k3d-molior-registry` and its
images stay; remove it with `k3d registry delete k3d-molior-registry`.
