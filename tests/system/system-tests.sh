#!/bin/sh
# System tests: create a throwaway k3d cluster with its own registry, deploy molior with the Helm chart,
# run the tests from a test runner pod inside the cluster, collect the results, remove everything.
#
# Usage (from anywhere, docker and k3d, helm, kubectl in PATH):
#   tests/system/system-tests.sh [pytest args, default: smoke]
# Environment:
#   RESULTS_DIR   where junit xml, screenshots, logs and coverage go (default: ./system-test-results)
#   KEEP=1        do not remove the cluster at the end (for debugging; remove it later with CLEANUP_ONLY=<id>)
#   CLEANUP_ONLY=<id>  only remove the cluster and registry of an earlier run (e.g. test-12345)
#   COVERAGE=0    skip the server coverage report
#
# Requires the image molior-base:dev (make docker-images-molior). Nothing outside docker is written except RESULTS_DIR,
# and the cluster, registry, their volumes and the temp files are removed at the end
# (also on failure or Ctrl-C). Stale clusters of earlier runs whose script is no longer running are removed first.
# The current kubectl context and ~/.kube/config are not touched.

set -eu

TOP=$(cd "$(dirname "$0")/../.." && pwd)
ID=test-$$                      # cluster k3d-$ID, registry k3d-$ID-registry
RESULTS_DIR=$(realpath -m "${RESULTS_DIR:-system-test-results}")
KEEP=${KEEP:-0}
COVERAGE=${COVERAGE:-1}
WORK=""

log() { echo "== $(date -u +%H:%M:%S) $*"; }

# remove cluster, registry and registry volume of one run id
remove_run() {
    vols=$(docker inspect "k3d-$1-registry" --format '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}} {{end}}{{end}}' 2>/dev/null || true)
    k3d cluster delete "$1" >/dev/null 2>&1 || true
    k3d registry delete "k3d-$1-registry" >/dev/null 2>&1 || true
    for v in $vols; do docker volume rm "$v" >/dev/null 2>&1 || true; done
}

cleanup() {
    rc=$?
    set +e
    if [ "$KEEP" = 1 ]; then
        log "KEEP=1: cluster $ID kept, KUBECONFIG=$WORK/kubeconfig; remove with: CLEANUP_ONLY=$ID $0"
    else
        log "removing cluster $ID"
        remove_run "$ID"
        [ -n "$WORK" ] && rm -rf "$WORK"
    fi
    log "exit $rc, results in $RESULTS_DIR"
    exit $rc
}

# remove leftovers of earlier runs whose script process is gone
remove_stale() {
    for name in $(k3d cluster list -o json 2>/dev/null | python3 -c 'import json,sys; [print(c["name"]) for c in json.load(sys.stdin)]'); do
        case "$name" in
            test-[0-9]*) pid=${name#test-}
                         if ! kill -0 "$pid" 2>/dev/null; then log "removing stale cluster $name"; remove_run "$name"; fi ;;
        esac
    done
    for name in $(k3d registry list -o json 2>/dev/null | python3 -c 'import json,sys; [print(r["name"]) for r in json.load(sys.stdin)]'); do
        case "$name" in
            k3d-test-[0-9]*-registry) pid=${name#k3d-test-}; pid=${pid%-registry}
                         if ! kill -0 "$pid" 2>/dev/null; then log "removing stale registry $name"; remove_run "test-$pid"; fi ;;
        esac
    done
}

if [ -n "${CLEANUP_ONLY:-}" ]; then
    remove_run "$CLEANUP_ONLY"
    exit 0
fi

for tool in docker k3d helm kubectl python3; do
    command -v $tool >/dev/null || { echo "E: $tool not found in PATH"; exit 1; }
done
docker image inspect molior-base:dev >/dev/null 2>&1 || { echo "E: image molior-base:dev missing, run: make docker-images-molior"; exit 1; }

remove_stale
trap cleanup EXIT
trap 'exit 130' INT TERM

WORK=$(mktemp -d /tmp/molior-$ID.XXXXXX)
export KUBECONFIG=$WORK/kubeconfig
mkdir -p "$RESULTS_DIR"
PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
REGISTRY=k3d-$ID-registry         # name inside the cluster (and in the chart), port 5000 there, $PORT on the host

log "registry $REGISTRY on 127.0.0.1:$PORT"
k3d registry create "$ID-registry" --port "127.0.0.1:$PORT" >/dev/null

# Inside the docker network the registry listens on 5000, only the host has $PORT. Molior pushes the build images
# itself (create-docker.sh, podman) to registry.server, so the chart gets $REGISTRY:5000, and containerd needs a
# mirror for that name (--registry-use only adds $REGISTRY:$PORT).
cat > "$WORK/registries.yaml" <<EOF
mirrors:
  "$REGISTRY:5000":
    endpoint:
      - http://$REGISTRY:5000
EOF

log "cluster $ID"
k3d cluster create "$ID" --registry-use "$REGISTRY:$PORT" --registry-config "$WORK/registries.yaml" \
    --no-lb --wait --timeout 300s \
    --kubeconfig-update-default=false --kubeconfig-switch-context=false \
    --k3s-arg "--disable=traefik@server:0" --k3s-arg "--disable=metrics-server@server:0" >/dev/null
k3d kubeconfig get "$ID" > "$KUBECONFIG"
chmod 600 "$KUBECONFIG"

log "building images (in parallel)"
cd "$TOP"
build() {  # build <dockerfile> <image>: push it to the test registry, keep no local tag (the build cache stays)
    docker build -q -f "$1" -t "localhost:$PORT/$2:dev" . >/dev/null 2>"$WORK/build-$2.err" &&
        docker push -q "localhost:$PORT/$2:dev" >/dev/null 2>>"$WORK/build-$2.err" &&
        docker rmi "localhost:$PORT/$2:dev" >/dev/null 2>>"$WORK/build-$2.err" || return 1
    log "  $2"
}
# the images do not depend on each other (molior-base:dev and debian:trixie-slim are their bases)
pids=""
for spec in tests/system/test.Dockerfile:molior docker/molior/postgres.Dockerfile:molior-postgres \
            docker/aptly/aptly.Dockerfile:aptly docker/aptly/nginx.Dockerfile:molior-nginx \
            tests/system/test-web.Dockerfile:molior-test-web; do
    build "${spec%%:*}" "${spec##*:}" &
    pids="$pids $!:${spec##*:}"
done
failed=""
for p in $pids; do
    wait "${p%%:*}" || failed="$failed ${p##*:}"
done
if [ -n "$failed" ]; then
    for image in $failed; do
        echo "E: building $image failed:"
        cat "$WORK/build-$image.err"
    done
    exit 1
fi

log "installing molior"
ADMIN_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(16))')
kubectl create namespace molior >/dev/null
kubectl -n molior create secret generic molior-passwords --from-literal=molior-password="$ADMIN_PASSWORD" \
    --from-literal=aptly-password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(16))')" \
    --from-literal=registry-password=unused >/dev/null
unset ADMIN_PASSWORD
timeout 900 helm install -n molior molior charts/ -f tests/system/values.yaml \
    --set registry.host="$REGISTRY" --set registry.port=5000 --wait --timeout 600s >/dev/null

log "test runner"
kubectl -n molior apply -f - >/dev/null <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: test-runner
spec:
  restartPolicy: Never
  containers:
    - name: tests
      image: $REGISTRY:5000/molior-test-web:dev
      env:
        - name: MOLIOR_URL
          value: http://web:8000
        - name: RESULTS_DIR
          value: /tmp/results
        - name: MOLIOR_ADMIN_PASSWORD
          valueFrom:
            secretKeyRef:
              name: molior-passwords
              key: molior-password
      volumeMounts:
        - mountPath: /dev/shm
          name: dshm
  volumes:
    - name: dshm
      emptyDir:
        medium: Memory
        sizeLimit: 1Gi
EOF
timeout 300 kubectl -n molior wait --for=condition=Ready pod/test-runner --timeout=280s >/dev/null
for i in $(seq 60); do
    kubectl -n molior exec test-runner -- curl -sf -o /dev/null http://web:8000/api/status && break
    sleep 5
done

[ $# -gt 0 ] || set -- smoke
log "running tests: $*"
set +e
timeout 1800 kubectl -n molior exec test-runner -- \
    python3 -m pytest -p no:cacheprovider -v --junitxml=/tmp/results/junit.xml "$@"
TESTS_RC=$?
set -e

log "collecting results"
kubectl -n molior cp test-runner:/tmp/results "$RESULTS_DIR" >/dev/null 2>&1 || true
kubectl -n molior logs deploy/molior -c molior-server > "$RESULTS_DIR/molior-server.log" 2>&1 || true
kubectl -n molior logs deploy/molior -c molior-postgres > "$RESULTS_DIR/molior-postgres.log" 2>&1 || true
kubectl -n molior logs deploy/aptly -c aptly-server > "$RESULTS_DIR/aptly-server.log" 2>&1 || true
kubectl -n molior cp -c molior-server "$(kubectl -n molior get pod -l app=molior -o jsonpath='{.items[0].metadata.name}')":/var/lib/molior/buildout \
    "$RESULTS_DIR/buildout" >/dev/null 2>&1 || true

if [ "$COVERAGE" = 1 ]; then
    log "server coverage"
    # stop molior (coverage is written at exit), the container restarts, then combine the data files
    restarts=$(kubectl -n molior get pod -l app=molior -o jsonpath='{.items[0].status.containerStatuses[?(@.name=="molior-server")].restartCount}')
    kubectl -n molior exec deploy/molior -c molior-server -- sh -c 'kill -TERM $(cat /var/run/molior.pid)' || true
    for i in $(seq 60); do
        now=$(kubectl -n molior get pod -l app=molior -o jsonpath='{.items[0].status.containerStatuses[?(@.name=="molior-server")].restartCount}')
        [ "$now" != "$restarts" ] && kubectl -n molior exec deploy/molior -c molior-server -- true 2>/dev/null && break
        sleep 2
    done
    kubectl -n molior exec deploy/molior -c molior-server -- su molior -c \
        'cd /var/lib/molior/coverage && COVERAGE_PROCESS_START= python3 -m coverage combine --rcfile=/etc/molior/coveragerc -q &&
         COVERAGE_PROCESS_START= python3 -m coverage report --rcfile=/etc/molior/coveragerc > report.txt;
         COVERAGE_PROCESS_START= python3 -m coverage xml --rcfile=/etc/molior/coveragerc -q -o coverage.xml' || true
    POD=$(kubectl -n molior get pod -l app=molior -o jsonpath='{.items[0].metadata.name}')
    kubectl -n molior cp -c molior-server "molior/$POD:/var/lib/molior/coverage/report.txt" "$RESULTS_DIR/coverage-report.txt" >/dev/null 2>&1 || true
    kubectl -n molior cp -c molior-server "molior/$POD:/var/lib/molior/coverage/coverage.xml" "$RESULTS_DIR/coverage.xml" >/dev/null 2>&1 || true
    tail -1 "$RESULTS_DIR/coverage-report.txt" 2>/dev/null || echo "coverage report missing"
fi

exit $TESTS_RC
