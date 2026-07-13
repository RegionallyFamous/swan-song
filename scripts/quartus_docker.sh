#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly TOOLCHAIN_DIR="$ROOT/toolchains/quartus-21.1.1"
readonly ARCHIVE_NAME=Quartus-lite-21.1.1.850-linux.tar
readonly DEFAULT_ARCHIVE="${HOME}/Downloads/${ARCHIVE_NAME}"
readonly IMAGE="${QUARTUS_IMAGE:-swan-song-quartus:21.1.1-850-cyclonev}"
readonly UBUNTU_AMD64="ubuntu@sha256:c664f8f86ed5a386b0a340d981b8f81714e21a8b9c73f658c4bea56aa179d54a"

usage() {
  cat <<'EOF'
Usage:
  scripts/quartus_docker.sh doctor
  scripts/quartus_docker.sh verify [Quartus-lite-21.1.1.850-linux.tar]
  QUARTUS_ACCEPT_EULA=1 scripts/quartus_docker.sh image [archive]
  scripts/quartus_docker.sh check-image
  scripts/quartus_docker.sh build [artifact-directory]

Environment:
  QUARTUS_IMAGE        Override the local image tag.
  QUARTUS_ACCEPT_EULA  Must be exactly 1 before the unattended installer runs.

The default archive is ~/Downloads/Quartus-lite-21.1.1.850-linux.tar.
The default artifact directory is build/quartus-docker/<Git-short-commit>.
EOF
}

fail() {
  echo "quartus_docker.sh: $*" >&2
  exit 1
}

require_docker() {
  command -v docker >/dev/null || fail "Docker is not installed"
  docker info >/dev/null 2>&1 || fail "Docker Desktop is not running"
}

doctor() {
  require_docker
  local architecture
  architecture="$(docker run --rm --platform linux/amd64 --network none \
    "$UBUNTU_AMD64" uname -m)"
  [[ "$architecture" == x86_64 ]] || fail "amd64 emulation returned $architecture"
  echo "Docker can start a pinned linux/amd64 Ubuntu 20.04 container ($architecture)"
  if [[ "$(uname -m)" == arm64 ]]; then
    echo "Host is Apple Silicon; Quartus execution remains best-effort until a full fit completes"
  fi
}

verify_archive() {
  local archive="${1:-$DEFAULT_ARCHIVE}"
  python3 "$ROOT/scripts/quartus_archive.py" verify "$archive"
}

inspect_image() {
  require_docker
  docker image inspect "$IMAGE" >/dev/null 2>&1 || fail "image does not exist: $IMAGE"

  local platform edition version device archive_sha1
  platform="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$IMAGE")"
  edition="$(docker image inspect --format '{{index .Config.Labels "com.swan-song.quartus.edition"}}' "$IMAGE")"
  version="$(docker image inspect --format '{{index .Config.Labels "com.swan-song.quartus.version"}}' "$IMAGE")"
  device="$(docker image inspect --format '{{index .Config.Labels "com.swan-song.quartus.device"}}' "$IMAGE")"
  archive_sha1="$(docker image inspect --format '{{index .Config.Labels "com.swan-song.quartus.archive-sha1"}}' "$IMAGE")"

  [[ "$platform" == linux/amd64 ]] || fail "image platform is $platform, expected linux/amd64"
  [[ "$edition" == Lite ]] || fail "image edition is $edition, expected Lite"
  [[ "$version" == 21.1.1.850 ]] || fail "image version is $version, expected 21.1.1.850"
  [[ "$device" == 5CEBA4F23C8 ]] || fail "image device is $device, expected 5CEBA4F23C8"
  [[ "$archive_sha1" == 789c1133d99fde7146fdb99c1f5dcb4d2e5cc0cc ]] \
    || fail "image archive provenance label is wrong: $archive_sha1"

  docker run --rm --platform linux/amd64 --network none \
    "$IMAGE" /usr/local/bin/toolchain-check
}

build_image() {
  local archive="${1:-$DEFAULT_ARCHIVE}"
  require_docker
  [[ "${QUARTUS_ACCEPT_EULA:-}" == 1 ]] || fail \
    "read the Quartus EULA, then set QUARTUS_ACCEPT_EULA=1 for unattended installation"

  local context
  context="$(mktemp -d "${TMPDIR:-/tmp}/swan-song-quartus-context.XXXXXX")"
  trap 'rm -rf "$context"' EXIT
  mkdir "$context/components"
  python3 "$ROOT/scripts/quartus_archive.py" extract "$archive" "$context/components"
  cp "$TOOLCHAIN_DIR/Dockerfile" "$context/Dockerfile"
  cp "$TOOLCHAIN_DIR/toolchain-check.sh" "$context/toolchain-check.sh"
  cp "$TOOLCHAIN_DIR/verify-toolchain.tcl" "$context/verify-toolchain.tcl"
  cp "$TOOLCHAIN_DIR/container-build-core.sh" "$context/container-build-core.sh"

  docker build \
    --platform linux/amd64 \
    --target runtime \
    --build-arg QUARTUS_ACCEPT_EULA=1 \
    --tag "$IMAGE" \
    --file "$context/Dockerfile" \
    "$context"

  inspect_image
  echo "built and verified $IMAGE"
}

build_core() {
  require_docker
  inspect_image

  local exclude_mif=':(exclude)src/fpga/apf/build_id.mif'
  git -C "$ROOT" diff --quiet -- . "$exclude_mif" || fail \
    "tracked source has unstaged changes; commit them before the fit"
  git -C "$ROOT" diff --cached --quiet -- . "$exclude_mif" || fail \
    "tracked source has staged changes; commit them before the fit"

  local short_commit output parent
  short_commit="$(git -C "$ROOT" rev-parse --short=12 HEAD)"
  output="${1:-$ROOT/build/quartus-docker/$short_commit}"
  mkdir -p "$output"
  if find "$output" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    fail "artifact directory must be empty: $output"
  fi
  output="$(cd "$output" && pwd -P)"

  docker run --rm \
    --platform linux/amd64 \
    --network none \
    --volume "$ROOT:/source:ro" \
    --volume "$output:/artifacts:rw" \
    "$IMAGE" \
    /usr/local/bin/container-build-core

  echo "fit/timing output: $output"
}

command="${1:-}"
case "$command" in
  doctor)
    [[ $# -eq 1 ]] || { usage >&2; exit 64; }
    doctor
    ;;
  verify)
    [[ $# -le 2 ]] || { usage >&2; exit 64; }
    verify_archive "${2:-$DEFAULT_ARCHIVE}"
    ;;
  image)
    [[ $# -le 2 ]] || { usage >&2; exit 64; }
    build_image "${2:-$DEFAULT_ARCHIVE}"
    ;;
  check-image)
    [[ $# -eq 1 ]] || { usage >&2; exit 64; }
    inspect_image
    ;;
  build)
    [[ $# -le 2 ]] || { usage >&2; exit 64; }
    build_core "${2:-}"
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 64
    ;;
esac
