#!/bin/sh
# Deploy tests: create a throwaway k3d cluster with its own registry, deploy molior with the Helm chart, map the
# molior API and the APT repos to host ports, and run pytest on the host: molior-deploy (molior-tools) needs root
# (sudo), loop devices, nbd, docker and virtualbox, so it cannot run in a pod of the cluster. Collects the results and
# removes everything.
#
# Usage (from anywhere; docker, k3d, helm, kubectl, python3 with pytest, pytest-timeout and requests, molior-deploy,
# and sudo without password for molior-deploy, the only command that runs as root):
#   tests/deploy/deploy-tests.sh [pytest args, default: test_deploy.py]
# Environment:
#   RESULTS_DIR   where junit xml, logs and coverage go; molior-deploy-output/: the deployments and their logs
#                 (default: ./deploy-test-results)
#   KEEP=1        do not remove the cluster at the end (for debugging; remove it later with CLEANUP_ONLY=<id>)
#   CLEANUP_ONLY=<id>  only remove the cluster and registry of an earlier run (e.g. deploy-12345)
#   COVERAGE=0    skip the server coverage report
#   TEST_TIMEOUT  seconds per test (pytest-timeout), a test that takes longer fails and the run goes on (default 3600)
#   RUN_TIMEOUT   seconds for the whole pytest run; when reached pytest is killed and the run fails (default 14400)
#
# Requires the image molior-base:dev (make deploy-tests builds it). The molior image is the one of the system tests
# (tests/system/test.Dockerfile: the working copy, with server coverage).
# The current kubectl context and ~/.kube/config are not touched.

set -eu

TOP=$(cd "$(dirname "$0")/../.." && pwd)
ID=deploy-$$                    # cluster k3d-$ID, registry k3d-$ID-registry
RESULTS_DIR=$(realpath -m "${RESULTS_DIR:-deploy-test-results}")
KEEP=${KEEP:-0}
COVERAGE=${COVERAGE:-1}
TEST_TIMEOUT=${TEST_TIMEOUT:-3600}
RUN_TIMEOUT=${RUN_TIMEOUT:-14400}
WORK=""

log() { echo "== $(date -u +%H:%M:%S) $*"; }

# remove cluster, registry, registry volume and docker network of one run id
remove_run() {
    vols=$(docker inspect "k3d-$1-registry" --format '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}} {{end}}{{end}}' 2>/dev/null || true)
    k3d cluster delete "$1" >/dev/null 2>&1 || true
    k3d registry delete "k3d-$1-registry" >/dev/null 2>&1 || true
    for v in $vols; do docker volume rm "$v" >/dev/null 2>&1 || true; done
    docker network rm "k3d-$1" >/dev/null 2>&1 || true
}

cleanup() {
    rc=$?
    set +e
    for p in $pids; do pkill -P "${p%%:*}" 2>/dev/null; kill "${p%%:*}" 2>/dev/null; done
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
            deploy-[0-9]*) pid=${name#deploy-}
                           if ! kill -0 "$pid" 2>/dev/null; then log "removing stale cluster $name"; remove_run "$name"; fi ;;
        esac
    done
    for name in $(k3d registry list -o json 2>/dev/null | python3 -c 'import json,sys; [print(r["name"]) for r in json.load(sys.stdin)]'); do
        case "$name" in
            k3d-deploy-[0-9]*-registry) pid=${name#k3d-deploy-}; pid=${pid%-registry}
                           if ! kill -0 "$pid" 2>/dev/null; then log "removing stale registry $name"; remove_run "deploy-$pid"; fi ;;
        esac
    done
    for name in $(docker network ls --format '{{.Name}}' --filter name=k3d-deploy-); do
        case "$name" in
            k3d-deploy-[0-9]*) pid=${name#k3d-deploy-}
                           if ! kill -0 "$pid" 2>/dev/null; then log "removing stale network $name"; remove_run "deploy-$pid"; fi ;;
        esac
    done
}

free_port() {
    python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'
}

if [ -n "${CLEANUP_ONLY:-}" ]; then
    remove_run "$CLEANUP_ONLY"
    exit 0
fi

for tool in docker k3d helm kubectl python3 sudo; do
    command -v $tool >/dev/null || { echo "E: $tool not found in PATH"; exit 1; }
done
python3 -c 'import pytest, pytest_timeout, requests' || { echo "E: python3 needs pytest, pytest-timeout and requests"; exit 1; }
[ -x /usr/sbin/molior-deploy ] || { echo "E: molior-deploy missing (make install-molior-tools)"; exit 1; }
sudo -n -l /usr/sbin/molior-deploy >/dev/null 2>&1 || {
    echo "E: sudo without password for molior-deploy needed, e.g. /etc/sudoers.d/molior-deploy:"
    echo "   $(id -un) ALL=(root) NOPASSWD: /usr/sbin/molior-deploy"
    exit 1
}
docker image inspect molior-base:dev >/dev/null 2>&1 || { echo "E: image molior-base:dev missing, run: make docker-images"; exit 1; }

remove_stale
pids=""             # image builds in the background (pid:image), stopped by cleanup
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

WORK=$(mktemp -d /tmp/molior-$ID.XXXXXX)
export KUBECONFIG=$WORK/kubeconfig
mkdir -p "$RESULTS_DIR"
PORT=$(free_port)
WEB_PORT=$(free_port)
REPO_PORT=$(free_port)
REGISTRY=k3d-$ID-registry         # name inside the cluster (and in the chart), port 5000 there, $PORT on the host

log "registry $REGISTRY on 127.0.0.1:$PORT"
k3d registry create "$ID-registry" --port "127.0.0.1:$PORT" >/dev/null

# molior pushes the build images itself to registry.server ($REGISTRY:5000): containerd needs a mirror for that name
cat > "$WORK/registries.yaml" <<EOF
mirrors:
  "$REGISTRY:5000":
    endpoint:
      - http://$REGISTRY:5000
EOF

# the NodePorts of the chart: web (molior API) 30080, repo (aptly nginx, the APT repos) 30088; k3d publishes them
# through its load balancer container (k3d-$ID-serverlb), so no --no-lb here (unlike system-tests.sh)
log "cluster $ID, molior on 127.0.0.1:$WEB_PORT, APT repos on 127.0.0.1:$REPO_PORT"
TMPDIR=$WORK k3d cluster create "$ID" --registry-use "$REGISTRY:$PORT" --registry-config "$WORK/registries.yaml" \
    --wait --timeout 300s \
    -p "127.0.0.1:$WEB_PORT:30080@server:0" -p "127.0.0.1:$REPO_PORT:30088@server:0" \
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
for spec in tests/system/test.Dockerfile:molior docker/molior/postgres.Dockerfile:molior-postgres \
            docker/aptly/aptly.Dockerfile:aptly docker/aptly/nginx.Dockerfile:molior-nginx; do
    build "${spec%%:*}" "${spec##*:}" &
    pids="$pids $!:${spec##*:}"
done
failed=""
for p in $pids; do
    wait "${p%%:*}" || failed="$failed ${p##*:}"
done
pids=""
if [ -n "$failed" ]; then
    for image in $failed; do
        echo "E: building $image failed:"
        cat "$WORK/build-$image.err"
    done
    exit 1
fi

log "installing molior"
MOLIOR_ADMIN_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(16))')
kubectl create namespace molior >/dev/null
kubectl -n molior create secret generic molior-passwords --from-literal=molior-password="$MOLIOR_ADMIN_PASSWORD" \
    --from-literal=aptly-password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(16))')" \
    --from-literal=registry-password=unused >/dev/null
timeout --foreground 900 helm install -n molior molior charts/ -f tests/deploy/values.yaml \
    --set registry.host="$REGISTRY" --set registry.port=5000 \
    --set aptly.publicUrl="http://127.0.0.1:$REPO_PORT" --wait --timeout 600s >/dev/null

export MOLIOR_URL=http://127.0.0.1:$WEB_PORT
export APTLY_URL=http://127.0.0.1:$REPO_PORT
export MOLIOR_ADMIN_PASSWORD
export RESULTS_DIR
for i in $(seq 60); do
    curl -sf -o /dev/null "$MOLIOR_URL/api/status" && break
    sleep 5
done
curl -sf -o /dev/null "$MOLIOR_URL/api/status" || { echo "E: molior not reachable on $MOLIOR_URL"; exit 1; }

[ $# -gt 0 ] || set -- test_deploy.py
log "running tests: $*"
# colors only when this script writes to a terminal, not into logs or CI (as the system tests); result lines with
# start time, number and time of each test: tests/system/pytest_output.py, 140 columns as in the system test pod
color=no
[ -t 1 ] && color=yes
set +e
(cd tests/deploy && PYTHONPATH="$TOP/tests/system" COLUMNS=140 timeout --foreground "$RUN_TIMEOUT" \
    python3 -m pytest -p no:cacheprovider -p pytest_output -v --color=$color \
    --timeout="$TEST_TIMEOUT" --junitxml="$RESULTS_DIR/junit.xml" "$@")
TESTS_RC=$?
set -e

log "collecting results"
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
    kubectl -n molior cp -c molior-server "molior/$POD:/var/lib/molior/coverage/.coverage" "$RESULTS_DIR/coverage.data" >/dev/null 2>&1 || true
    tail -1 "$RESULTS_DIR/coverage-report.txt" 2>/dev/null || echo "coverage report missing"
fi

exit $TESTS_RC
