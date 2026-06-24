# Development Setup

This guide covers running the full Molior stack locally using k3d (Kubernetes in Docker).

## Prerequisites

- Linux host with `podman` or `docker` installed
- `kubectl` and `helm` available in `PATH`
- `k3d`, install it with:

```sh
make install-k3d
```

> This downloads the k3d binary to `~/.local/bin/k3d`. Make sure `~/.local/bin` is in your `PATH`.

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

---

## 2. Build the Docker images

Build all local development images:

```sh
make docker-images
```

This builds: `molior`, `molior-postgres`, `molior-nginx`, `molior-web`, `aptly`.

Individual images can also be built separately:

```sh
make docker-molior
make docker-web
make docker-aptly
```

---

## 3. Push images into the cluster

Tag and push the local images into the k3d registry so the cluster can use them:

```sh
make deploy-cluster
```

Individual images can be pushed separately, e.g.:

```sh
make deploy-image-molior
make deploy-image-aptly
```

---

## 4. Install the Helm chart

Deploy Molior into the cluster:

```sh
make install-cluster
```

Installs the `charts/` Helm chart into the cluster.

---

## 5. Monitor Kubernetes pods

```sh
make watch
```

Once all pods are running, Molior is available at **http://localhost:8000** and the Aptly repository at **http://localhost:8080**.

---

## Common workflows

### Rebuild and redeploy everything

```sh
make docker-images
make redeploy-cluster
```

### Reinstall the Helm chart only (no image rebuild)

```sh
make reinstall-cluster
```

### View logs

```sh
make logs          # molior + aptly combined
make logs-molior
make logs-aptly
```

### Open a shell in the molior pod

```sh
make shell-molior
```

### Restart the molior pod

```sh
make restart-molior
```

---

## Teardown

```sh
make clean
```

This deletes the k3d cluster, the local registry, and the `molior-base` Docker image. All persistent data including the database and Molior repositories will be lost.
