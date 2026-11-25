#!/bin/sh
# Install the tools the system tests and the image build need on a CI runner (docker host).
# Usage: .github/scripts/install-tools.sh <bin dir> [helm]
#   helm: only helm (the helm chart job), else everything:
#   - docker (docker.io) and python3 when missing (apt, needs sudo)
#   - qemu user emulation with binfmt handlers (arm builds run on the amd64 node), checked with an arm64 and an armhf
#     container. The handlers need the F flag: the build containers do not have the qemu binary.
#     Debian: qemu-user-static + binfmt-support; Ubuntu (26.04): qemu-user-binfmt (qemu-user-static is only a virtual
#     package there).
#   - k3d, helm and kubectl in <bin dir> (pinned versions, checksums verified)
# Versions come from the environment: K3D_VERSION, HELM_VERSION, KUBECTL_VERSION.
set -eu

BIN=$1
ONLY=${2:-}
mkdir -p "$BIN"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT

install_helm() {
    echo "== helm $HELM_VERSION"
    curl -fsSL -o "$T/helm.tar.gz" "https://get.helm.sh/helm-$HELM_VERSION-linux-amd64.tar.gz"
    echo "$(curl -fsSL "https://get.helm.sh/helm-$HELM_VERSION-linux-amd64.tar.gz.sha256sum" | cut -d' ' -f1)  $T/helm.tar.gz" | sha256sum -c -
    tar -xzf "$T/helm.tar.gz" -C "$T" linux-amd64/helm
    install -m 755 "$T/linux-amd64/helm" "$BIN/helm"
    "$BIN/helm" version --short
}

: "${HELM_VERSION:?}"
if [ "$ONLY" = helm ]; then
    install_helm
    exit 0
fi
: "${K3D_VERSION:?}" "${KUBECTL_VERSION:?}"

pkgs=""
command -v docker >/dev/null || pkgs="$pkgs docker.io"
command -v python3 >/dev/null || pkgs="$pkgs python3"
qemu=0
[ -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ] && [ -e /proc/sys/fs/binfmt_misc/qemu-arm ] || qemu=1
if [ -n "$pkgs" ] || [ $qemu = 1 ]; then
    sudo apt-get update -q
    if [ $qemu = 1 ]; then
        # the package with an installation candidate (a virtual package has "Candidate: (none)")
        if apt-cache policy qemu-user-binfmt 2>/dev/null | grep -q 'Candidate: [0-9]'; then
            pkgs="$pkgs qemu-user-binfmt"
        else
            pkgs="$pkgs qemu-user-static binfmt-support"
        fi
    fi
    echo "== installing$pkgs"
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends $pkgs
    # the packages register the handlers with systemd-binfmt; make sure they are loaded
    if [ $qemu = 1 ] && ! [ -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ]; then
        sudo systemctl restart systemd-binfmt 2>/dev/null || sudo update-binfmts --enable 2>/dev/null || true
    fi
fi
docker version --format 'docker {{.Server.Version}}'

echo "== qemu binfmt handlers"
for arch in aarch64 arm; do
    f=/proc/sys/fs/binfmt_misc/qemu-$arch
    [ -e "$f" ] || { echo "E: $f missing (qemu binfmt handler not registered)"; exit 1; }
    grep -E '^(enabled|interpreter|flags)' "$f" | sed "s/^/  qemu-$arch: /"
    grep -q '^flags:.*F' "$f" || { echo "E: qemu-$arch is registered without the F flag"; exit 1; }
done
for platform in linux/arm64 linux/arm/v7; do
    m=$(docker run --rm --platform "$platform" debian:trixie-slim uname -m)
    echo "  $platform: $m"
    case "$platform:$m" in
        linux/arm64:aarch64|linux/arm/v7:armv7l|linux/arm/v7:armv8l) ;;
        *) echo "E: $platform container runs as $m"; exit 1 ;;
    esac
done

echo "== k3d $K3D_VERSION"
curl -fsSL -o "$T/k3d-linux-amd64" "https://github.com/k3d-io/k3d/releases/download/$K3D_VERSION/k3d-linux-amd64"
# checksums.txt names the file _dist/k3d-linux-amd64
echo "$(curl -fsSL "https://github.com/k3d-io/k3d/releases/download/$K3D_VERSION/checksums.txt" | awk '$2 ~ /(^|\/)k3d-linux-amd64$/ {print $1}')  $T/k3d-linux-amd64" | sha256sum -c -
install -m 755 "$T/k3d-linux-amd64" "$BIN/k3d"

install_helm

echo "== kubectl $KUBECTL_VERSION"
curl -fsSL -o "$T/kubectl" "https://dl.k8s.io/release/$KUBECTL_VERSION/bin/linux/amd64/kubectl"
echo "$(curl -fsSL "https://dl.k8s.io/release/$KUBECTL_VERSION/bin/linux/amd64/kubectl.sha256")  $T/kubectl" | sha256sum -c -
install -m 755 "$T/kubectl" "$BIN/kubectl"

"$BIN/k3d" version | head -1
"$BIN/kubectl" version --client | head -1
