#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly ROOT
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
  docker info >/dev/null 2>&1 || fail "Docker daemon is not reachable"
}

doctor() {
  require_docker
  local architecture
  architecture="$(docker run --rm --platform linux/amd64 --network none \
    --entrypoint /usr/bin/uname "$UBUNTU_AMD64" -m)"
  [[ "$architecture" == x86_64 ]] || fail "linux/amd64 probe returned $architecture"
  echo "Docker can start a pinned linux/amd64 Ubuntu 20.04 container ($architecture)"
  if [[ "$(uname -m)" == arm64 ]]; then
    echo "Host is Apple Silicon; Quartus execution remains best-effort until a full fit completes"
  fi
}

verify_archive() {
  local archive="${1:-$DEFAULT_ARCHIVE}"
  python3 "$ROOT/scripts/quartus_archive.py" verify "$archive"
}

sha256_file() {
  python3 - "$1" <<'PY'
import hashlib
from pathlib import Path
import sys

path = Path(sys.argv[1])
digest = hashlib.sha256()
with path.open("rb") as source:
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(chunk)
print(digest.hexdigest())
PY
}

verify_container_toolchain_payload() {
  local image_id="$1"
  local temporary container_id index checkout embedded extracted expected actual
  local checkout_files=(
    "$TOOLCHAIN_DIR/container-build-core.sh"
    "$TOOLCHAIN_DIR/toolchain-check.sh"
    "$TOOLCHAIN_DIR/verify-toolchain.tcl"
  )
  local embedded_files=(
    /usr/local/bin/container-build-core
    /usr/local/bin/toolchain-check
    /usr/local/share/swan-song/verify-toolchain.tcl
  )
  temporary="$(mktemp -d "${TMPDIR:-/tmp}/swan-song-helper-check.XXXXXX")"

  if ! container_id="$(docker create --platform linux/amd64 --network none \
      --entrypoint /bin/true "$image_id")"; then
    rm -rf "$temporary"
    fail "could not create a container to inspect the embedded toolchain payload"
  fi

  for index in "${!checkout_files[@]}"; do
    checkout="${checkout_files[$index]}"
    embedded="${embedded_files[$index]}"
    extracted="$temporary/$index"
    if ! docker cp "$container_id:$embedded" "$extracted"; then
      docker rm -f "$container_id" >/dev/null 2>&1 || true
      rm -rf "$temporary"
      fail "could not extract embedded toolchain payload: $embedded"
    fi
    if [[ ! -f "$extracted" || -L "$extracted" ]]; then
      docker rm -f "$container_id" >/dev/null 2>&1 || true
      rm -rf "$temporary"
      fail "embedded toolchain payload is not a regular file: $embedded"
    fi
    expected="$(sha256_file "$checkout")"
    actual="$(sha256_file "$extracted")"
    if [[ "$actual" != "$expected" ]]; then
      docker rm -f "$container_id" >/dev/null 2>&1 || true
      rm -rf "$temporary"
      fail "embedded toolchain payload does not match checkout: $embedded"
    fi
  done

  if ! docker rm "$container_id" >/dev/null; then
    rm -rf "$temporary"
    fail "could not remove the toolchain-payload inspection container"
  fi
  rm -rf "$temporary"
}

resolve_image_id() {
  local image_id
  docker image inspect "$IMAGE" >/dev/null 2>&1 || fail "image does not exist: $IMAGE"
  image_id="$(docker image inspect --format '{{.Id}}' "$IMAGE")"
  [[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] \
    || fail "image has an invalid immutable ID: $image_id"
  printf '%s\n' "$image_id"
}

inspect_image() {
  local image_id="$1"
  local platform edition version device archive_sha1
  platform="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$image_id")"
  edition="$(docker image inspect --format '{{index .Config.Labels "com.swan-song.quartus.edition"}}' "$image_id")"
  version="$(docker image inspect --format '{{index .Config.Labels "com.swan-song.quartus.version"}}' "$image_id")"
  device="$(docker image inspect --format '{{index .Config.Labels "com.swan-song.quartus.device"}}' "$image_id")"
  archive_sha1="$(docker image inspect --format '{{index .Config.Labels "com.swan-song.quartus.archive-sha1"}}' "$image_id")"

  [[ "$platform" == linux/amd64 ]] || fail "image platform is $platform, expected linux/amd64"
  [[ "$edition" == Lite ]] || fail "image edition is $edition, expected Lite"
  [[ "$version" == 21.1.1.850 ]] || fail "image version is $version, expected 21.1.1.850"
  [[ "$device" == 5CEBA4F23C8 ]] || fail "image device is $device, expected 5CEBA4F23C8"
  [[ "$archive_sha1" == 789c1133d99fde7146fdb99c1f5dcb4d2e5cc0cc ]] \
    || fail "image archive provenance label is wrong: $archive_sha1"

  verify_container_toolchain_payload "$image_id"
  docker run --rm --platform linux/amd64 --network none \
    --user 0:0 \
    --entrypoint /usr/local/bin/toolchain-check \
    "$image_id"
}

check_image() {
  require_docker
  local image_id
  image_id="$(resolve_image_id)"
  inspect_image "$image_id"
  echo "verified $IMAGE as immutable image $image_id"
}

write_container_evidence() {
  local evidence_root="$1"
  local image_id="$2"
  local packages="$evidence_root/container-packages.tsv"
  local provenance="$evidence_root/container-provenance.json"
  local repo_digests

  docker run --rm --platform linux/amd64 --network none \
    --user 0:0 \
    --entrypoint /usr/bin/dpkg-query \
    "$image_id" -W '-f=${binary:Package}\t${Version}\t${Architecture}\n' \
    | LC_ALL=C sort > "$packages"
  repo_digests="$(docker image inspect \
    --format '{{range .RepoDigests}}{{println .}}{{end}}' "$image_id" \
    | LC_ALL=C sort -u)"
  python3 "$ROOT/scripts/quartus_container_provenance.py" create \
    --image-id "$image_id" \
    --repo-digests "$repo_digests" \
    --packages "$packages" \
    --output "$provenance"
}

merge_container_evidence() {
  local evidence_root="$1"
  local output="$2"
  local reserved source destination

  for reserved in container-packages.tsv container-provenance.json; do
    destination="$output/$reserved"
    if [[ -e "$destination" || -L "$destination" ]]; then
      fail "container created reserved provenance path: $reserved"
    fi
  done

  for reserved in container-packages.tsv container-provenance.json; do
    source="$evidence_root/$reserved"
    destination="$output/$reserved"
    if ! (umask 022; set -o noclobber; cat "$source" > "$destination"); then
      fail "could not install reserved provenance path without collision: $reserved"
    fi
  done
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

  check_image
  echo "built and verified $IMAGE"
}

build_core() (
  require_docker
  local image_id provenance_root container_status
  provenance_root=""
  # Invoked indirectly by the EXIT trap below.
  # shellcheck disable=SC2329
  cleanup_build_core() {
    local status=$?
    trap - EXIT
    if [[ -n "$provenance_root" ]] && ! rm -rf "$provenance_root"; then
      echo "quartus_docker.sh: could not remove host-only provenance directory" >&2
      if (( status == 0 )); then
        status=1
      fi
    fi
    exit "$status"
  }
  trap cleanup_build_core EXIT

  image_id="$(resolve_image_id)"
  inspect_image "$image_id"

  local exclude_mif=':(exclude)src/fpga/apf/build_id.mif'
  git -C "$ROOT" diff --quiet -- . "$exclude_mif" || fail \
    "tracked source has unstaged changes; commit them before the fit"
  git -C "$ROOT" diff --cached --quiet -- . "$exclude_mif" || fail \
    "tracked source has staged changes; commit them before the fit"

  local short_commit output
  short_commit="$(git -C "$ROOT" rev-parse --short=12 HEAD)"
  output="${1:-$ROOT/build/quartus-docker/$short_commit}"
  mkdir -p "$output"
  if find "$output" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    fail "artifact directory must be empty: $output"
  fi
  output="$(cd "$output" && pwd -P)"
  provenance_root="$(mktemp -d "${TMPDIR:-/tmp}/swan-song-container-evidence.XXXXXX")"
  write_container_evidence "$provenance_root" "$image_id"

  set +e
  docker run --rm \
    --platform linux/amd64 \
    --network none \
    --user 0:0 \
    --env "ARTIFACT_UID=$(id -u)" \
    --env "ARTIFACT_GID=$(id -g)" \
    --volume "$ROOT:/source:ro" \
    --volume "$output:/artifacts:rw" \
    --entrypoint /usr/local/bin/container-build-core \
    "$image_id"
  container_status=$?
  set -e

  merge_container_evidence "$provenance_root" "$output"
  if (( container_status != 0 )); then
    return "$container_status"
  fi

  python3 "$ROOT/scripts/quartus_fit_audit.py" \
    --artifacts "$output" \
    --output "$output/quartus-audit-candidate.json"

  echo "audited non-release fit/timing candidate: $output"
)

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
    check_image
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
