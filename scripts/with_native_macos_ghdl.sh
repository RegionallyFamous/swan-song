#!/usr/bin/env bash
# Run the repository's Docker-shaped GHDL tests with a caller-supplied native
# macOS GHDL 6.0.0 LLVM bundle. Docker remains the default everywhere else.
set -euo pipefail

readonly EXPECTED_IMAGE_TAG="ghdl/ghdl:6.0.0-llvm-ubuntu-24.04"
readonly EXPECTED_IMAGE_DIGEST="ghdl/ghdl@sha256:8b3ec37c3873b2eee9387759e66c50830c15ae5b7b533badaa97ce007a0f8022"
readonly EXPECTED_VERSION_LINE="GHDL 6.0.0 (6.0.0.r0.ge589c698c) [Dunoon edition]"

fail() {
  printf 'with_native_macos_ghdl.sh: %s\n' "$*" >&2
  exit 125
}

usage() {
  cat <<'EOF'
Usage:
  scripts/with_native_macos_ghdl.sh [--bundle DIR | --ghdl FILE] -- COMMAND [ARG ...]

Explicitly run Docker-shaped Swan Song GHDL tests with native macOS GHDL.
The tool never downloads GHDL. Supply the official extracted Apple-Silicon
GHDL 6.0.0 LLVM bundle with --bundle/SWAN_GHDL_BUNDLE, or its bin/ghdl
driver with --ghdl/SWAN_GHDL. If neither is set, a native ghdl already on PATH
is used.

Examples:
  scripts/with_native_macos_ghdl.sh --bundle /absolute/ghdl-bundle -- \
    sim/rtl/run_soc_control_tb.sh
  SWAN_GHDL_BUNDLE=/absolute/ghdl-bundle \
    scripts/with_native_macos_ghdl.sh -- make regression
EOF
}

canonical_existing() {
  local path=$1 resolved
  resolved=$(realpath "$path" 2>/dev/null) || return 1
  [[ -e $resolved ]] || return 1
  printf '%s' "$resolved"
}

map_container_path() {
  local value=$1 i guest host
  for i in "${!SWAN_MOUNT_HOSTS[@]}"; do
    guest=${SWAN_MOUNT_GUESTS[$i]}
    host=${SWAN_MOUNT_HOSTS[$i]}
    if [[ $value == "$guest" ]]; then
      printf '%s' "$host"
      return 0
    fi
    if [[ $guest != / && $value == "$guest"/* ]]; then
      printf '%s/%s' "$host" "${value#"$guest"/}"
      return 0
    fi
  done
  return 1
}

map_ghdl_argument() {
  local value=$1 prefix suffix mapped
  if [[ $value == /* ]]; then
    mapped=$(map_container_path "$value") || \
      fail "absolute argument is outside the declared mounts: $value"
    printf '%s' "$mapped"
    return
  fi
  if [[ $value == *=/* ]]; then
    prefix=${value%%=*}
    suffix=${value#*=}
    mapped=$(map_container_path "$suffix") || \
      fail "absolute option value is outside the declared mounts: $prefix"
    printf '%s=%s' "$prefix" "$mapped"
    return
  fi
  case "$value" in
    -P/*|-I/*)
      prefix=${value:0:2}
      suffix=${value:2}
      mapped=$(map_container_path "$suffix") || \
        fail "absolute search path is outside the declared mounts: $prefix"
      printf '%s%s' "$prefix" "$mapped"
      ;;
    *)
      printf '%s' "$value"
      ;;
  esac
}

add_mount() {
  local value=$1 host guest rest i existing
  [[ $value == *:* ]] || fail "volume must be HOST:GUEST"
  host=${value%%:*}
  rest=${value#*:}
  [[ $rest != *:* ]] || fail "volume options and additional ':' fields are unsupported"
  guest=$rest
  [[ $host == /* ]] || fail "volume host must be an absolute path"
  [[ $guest == /* ]] || fail "volume guest must be an absolute path"
  [[ $host != *'/../'* && $host != */.. && $host != *'/./'* ]] || \
    fail "volume host must not contain traversal components"
  [[ $guest != *'/../'* && $guest != */.. && $guest != *'/./'* ]] || \
    fail "volume guest must not contain traversal components"
  host=$(canonical_existing "$host") || fail "volume host does not exist"
  [[ -d $host ]] || fail "volume host must be a directory"
  if [[ $guest != / ]]; then
    guest=${guest%/}
  fi
  for i in "${!SWAN_MOUNT_GUESTS[@]}"; do
    existing=${SWAN_MOUNT_GUESTS[$i]}
    [[ $guest != "$existing" ]] || fail "duplicate guest mount: $guest"
    [[ $guest != "$existing"/* && $existing != "$guest"/* ]] || \
      fail "overlapping guest mounts are unsupported"
  done
  SWAN_MOUNT_HOSTS[${#SWAN_MOUNT_HOSTS[@]}]=$host
  SWAN_MOUNT_GUESTS[${#SWAN_MOUNT_GUESTS[@]}]=$guest
}

docker_shim() {
  [[ ${SWAN_NATIVE_GHDL_ACTIVE:-} == 1 ]] || \
    fail "the Docker shim may only run inside the explicit native-GHDL wrapper"
  [[ -x ${SWAN_NATIVE_GHDL_DRIVER:-} ]] || fail "temporary GHDL driver is unavailable"
  [[ -d ${SWAN_NATIVE_GHDL_BUNDLE:-}/lib/ghdl ]] || fail "native GHDL bundle is unavailable"
  export GHDL_PREFIX="$SWAN_NATIVE_GHDL_BUNDLE/lib/ghdl"
  [[ ${1:-} == run ]] || fail "only 'docker run' is supported"
  shift

  local saw_rm=0 saw_platform=0 saw_workdir=0
  local platform='' workdir='' image='' option value command_name
  local mapped_workdir mapped_workdir_real arg
  SWAN_MOUNT_HOSTS=()
  SWAN_MOUNT_GUESTS=()

  while (($#)); do
    case "$1" in
      --rm)
        ((saw_rm == 0)) || fail "duplicate --rm"
        saw_rm=1
        shift
        ;;
      --platform|-w|--workdir|-v|--volume)
        option=$1
        (($# >= 2)) || fail "missing value for $option"
        value=$2
        shift 2
        case "$option" in
          --platform)
            ((saw_platform == 0)) || fail "duplicate platform option"
            saw_platform=1
            platform=$value
            ;;
          -w|--workdir)
            ((saw_workdir == 0)) || fail "duplicate workdir option"
            saw_workdir=1
            workdir=$value
            ;;
          -v|--volume) add_mount "$value" ;;
        esac
        ;;
      --platform=*)
        ((saw_platform == 0)) || fail "duplicate platform option"
        saw_platform=1
        platform=${1#*=}
        shift
        ;;
      --workdir=*)
        ((saw_workdir == 0)) || fail "duplicate workdir option"
        saw_workdir=1
        workdir=${1#*=}
        shift
        ;;
      --volume=*)
        add_mount "${1#*=}"
        shift
        ;;
      --*)
        fail "unsupported docker option: $1"
        ;;
      -*)
        fail "unsupported docker option: $1"
        ;;
      *)
        image=$1
        shift
        break
        ;;
    esac
  done

  ((saw_rm == 1)) || fail "docker run must include --rm"
  [[ $platform == linux/amd64 ]] || fail "docker run must select --platform linux/amd64"
  ((${#SWAN_MOUNT_HOSTS[@]} > 0)) || fail "docker run must declare an absolute volume mount"
  [[ -n $workdir ]] || fail "docker run must declare a workdir"
  [[ $image == "$EXPECTED_IMAGE_TAG" || $image == "$EXPECTED_IMAGE_DIGEST" ]] || \
    fail "unsupported GHDL image identity"
  (($#)) || fail "missing container command"

  mapped_workdir=$(map_container_path "$workdir") || \
    fail "workdir is outside the declared mounts"
  [[ -d $mapped_workdir ]] || fail "mapped workdir does not exist"
  mapped_workdir_real=$(cd "$mapped_workdir" && pwd -P) || fail "cannot enter mapped workdir"
  mapped_workdir=$mapped_workdir_real
  cd "$mapped_workdir"

  command_name=$1
  shift
  SWAN_MAPPED_ARGS=()
  for arg in "$@"; do
    SWAN_MAPPED_ARGS[${#SWAN_MAPPED_ARGS[@]}]=$(map_ghdl_argument "$arg")
  done

  case "$command_name" in
    ghdl)
      exec "$SWAN_NATIVE_GHDL_DRIVER" "${SWAN_MAPPED_ARGS[@]}"
      ;;
    ./*)
      [[ $command_name =~ ^\./[A-Za-z0-9_.-]+$ ]] || \
        fail "generated executable must be a single safe relative filename"
      [[ -f $command_name && -x $command_name ]] || \
        fail "generated executable is not an executable file"
      exec "$command_name" "${SWAN_MAPPED_ARGS[@]}"
      ;;
    *)
      fail "unsupported container command: $command_name"
      ;;
  esac
}

if [[ $(basename "$0") == docker ]]; then
  docker_shim "$@"
  exit 125
fi

bundle_arg=
ghdl_arg=
while (($#)); do
  case "$1" in
    --bundle)
      (($# >= 2)) || fail "--bundle requires a path"
      bundle_arg=$2
      shift 2
      ;;
    --ghdl)
      (($# >= 2)) || fail "--ghdl requires a path"
      ghdl_arg=$2
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    *)
      fail "unknown wrapper option: $1"
      ;;
  esac
done

[[ $(uname -s) == Darwin ]] || fail "native fallback is supported only on macOS"
[[ $(uname -m) == arm64 ]] || fail "native fallback requires Apple Silicon (arm64)"
[[ -z $bundle_arg || -z $ghdl_arg ]] || fail "choose either --bundle or --ghdl"
(($#)) || fail "missing command after --"

if [[ -z $bundle_arg && -z $ghdl_arg ]]; then
  bundle_arg=${SWAN_GHDL_BUNDLE:-}
  ghdl_arg=${SWAN_GHDL:-}
fi
if [[ -n $bundle_arg ]]; then
  bundle_arg=$(canonical_existing "$bundle_arg") || fail "GHDL bundle does not exist"
  [[ -d $bundle_arg ]] || fail "GHDL bundle must be a directory"
  ghdl_arg=$bundle_arg/bin/ghdl
elif [[ -z $ghdl_arg ]]; then
  ghdl_arg=$(command -v ghdl 2>/dev/null || true)
  [[ -n $ghdl_arg ]] || fail "no native GHDL supplied or found on PATH"
fi

ghdl_arg=$(canonical_existing "$ghdl_arg") || fail "GHDL driver does not exist"
[[ -f $ghdl_arg && -x $ghdl_arg ]] || fail "GHDL driver must be an executable file"
bundle_arg=$(cd "$(dirname "$ghdl_arg")/.." && pwd -P) || fail "cannot resolve GHDL bundle"
[[ -d $bundle_arg/lib/ghdl ]] || fail "GHDL bundle is missing lib/ghdl"
[[ -f $bundle_arg/bin/ghdl1-llvm && -x $bundle_arg/bin/ghdl1-llvm ]] || \
  fail "GHDL bundle is missing executable bin/ghdl1-llvm"
[[ -f $bundle_arg/bin/ghwdump && -x $bundle_arg/bin/ghwdump ]] || \
  fail "GHDL bundle is missing executable bin/ghwdump"
if [[ -f $bundle_arg/bin/libgcc_s.1.1.dylib ]]; then
  libgcc_arg=$bundle_arg/bin/libgcc_s.1.1.dylib
elif [[ -f $bundle_arg/lib/libgcc_s.1.1.dylib ]]; then
  libgcc_arg=$bundle_arg/lib/libgcc_s.1.1.dylib
else
  fail "GHDL bundle is missing libgcc_s.1.1.dylib"
fi

script_path=$(canonical_existing "${BASH_SOURCE[0]}") || fail "cannot resolve wrapper path"
state_dir=$(mktemp -d "${TMPDIR:-/tmp}/swan-song-native-ghdl.XXXXXX") || \
  fail "cannot create temporary native-GHDL directory"
# shellcheck disable=SC2329 # invoked by the EXIT trap
cleanup() {
  rm -rf "$state_dir"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
mkdir -p "$state_dir/bin"
cp "$ghdl_arg" "$state_dir/bin/ghdl" || fail "cannot copy GHDL driver"
cp "$bundle_arg/bin/ghdl1-llvm" "$state_dir/bin/ghdl1-llvm" || \
  fail "cannot copy GHDL LLVM backend"
cp "$bundle_arg/bin/ghwdump" "$state_dir/bin/ghwdump" || fail "cannot copy ghwdump"
cp "$libgcc_arg" "$state_dir/bin/libgcc_s.1.1.dylib" || \
  fail "cannot copy GHDL runtime library"
if command -v xattr >/dev/null 2>&1; then
  xattr -c "$state_dir/bin/ghdl" || fail "cannot clear copied-driver attributes"
  xattr -c "$state_dir/bin/ghdl1-llvm" || fail "cannot clear copied-backend attributes"
  xattr -c "$state_dir/bin/ghwdump" || fail "cannot clear copied-ghwdump attributes"
  xattr -c "$state_dir/bin/libgcc_s.1.1.dylib" || \
    fail "cannot clear copied-library attributes"
fi
chmod 700 "$state_dir/bin/ghdl" "$state_dir/bin/ghdl1-llvm" "$state_dir/bin/ghwdump"
ln -s "$script_path" "$state_dir/bin/docker"

export SWAN_NATIVE_GHDL_ACTIVE=1
export SWAN_NATIVE_GHDL_DRIVER="$state_dir/bin/ghdl"
export SWAN_NATIVE_GHDL_BUNDLE="$bundle_arg"
export GHDL_PREFIX="$bundle_arg/lib/ghdl"
export PATH="$state_dir/bin:$PATH"

version_output=$($SWAN_NATIVE_GHDL_DRIVER --version 2>&1) || fail "native GHDL version probe failed"
version_line=${version_output%%$'\n'*}
[[ $version_line == "$EXPECTED_VERSION_LINE" ]] || \
  fail "native GHDL must match the official v6.0.0 e589c698c build"
grep -Eiq 'llvm.*code generator|code generator.*llvm' <<<"$version_output" || \
  fail "native GHDL must use the LLVM code generator"

set +e
"$@"
command_status=$?
set -e
exit "$command_status"
