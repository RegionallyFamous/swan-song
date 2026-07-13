#!/usr/bin/env bash
set -euo pipefail

readonly source_root=/source
readonly artifact_root=/artifacts

test -d "$source_root/.git" || {
  echo "read-only Git checkout was not mounted at $source_root" >&2
  exit 71
}
test -d "$artifact_root" && test -w "$artifact_root" || {
  echo "writable artifact directory was not mounted at $artifact_root" >&2
  exit 72
}
if find "$artifact_root" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
  echo "artifact directory must be empty: $artifact_root" >&2
  exit 73
fi
case "${ARTIFACT_UID:-}" in
  (*[!0-9]*|'') echo "ARTIFACT_UID must be a numeric host user ID" >&2; exit 79 ;;
esac
case "${ARTIFACT_GID:-}" in
  (*[!0-9]*|'') echo "ARTIFACT_GID must be a numeric host group ID" >&2; exit 80 ;;
esac

work_root=""
cleanup() {
  local status=$?
  trap - EXIT
  if [[ -n "$work_root" ]] && ! rm -rf "$work_root"; then
    echo "failed to remove temporary Quartus work tree: $work_root" >&2
    if (( status == 0 )); then
      status=81
    fi
  fi
  if ! chown -R --no-dereference \
    "$ARTIFACT_UID:$ARTIFACT_GID" "$artifact_root"; then
    echo "failed to return Quartus artifacts to $ARTIFACT_UID:$ARTIFACT_GID" >&2
    if (( status == 0 )); then
      status=82
    fi
  fi
  exit "$status"
}
trap cleanup EXIT

/usr/local/bin/toolchain-check

exclude_mif=':(exclude)src/fpga/apf/build_id.mif'
git_source=(git -c "safe.directory=$source_root" -C "$source_root")
"${git_source[@]}" diff --quiet -- . "$exclude_mif" || {
  echo "tracked source has unstaged changes; refusing a non-reproducible fit" >&2
  exit 74
}
"${git_source[@]}" diff --cached --quiet -- . "$exclude_mif" || {
  echo "tracked source has staged changes; refusing a non-reproducible fit" >&2
  exit 75
}

source_commit="$("${git_source[@]}" rev-parse --verify HEAD)"
source_epoch="$("${git_source[@]}" show -s --format=%ct "$source_commit")"
case "$source_commit" in
  (*[!0-9a-f]*|'') echo "invalid Git source commit: $source_commit" >&2; exit 76 ;;
esac
case "$source_epoch" in
  (*[!0-9]*|'') echo "invalid Git source epoch: $source_epoch" >&2; exit 77 ;;
esac

work_root="$(mktemp -d /tmp/swan-song-quartus.XXXXXX)"
mkdir "$work_root/repo"

# Build the exact committed tree. This excludes untracked host files and old
# Quartus databases without mutating the mounted checkout.
"${git_source[@]}" archive --format=tar "$source_commit" \
  | tar -xf - -C "$work_root/repo"

cd "$work_root/repo"
export QUARTUS_SH=/opt/intelFPGA/quartus/bin/quartus_sh
export SWANSONG_SOURCE_COMMIT="$source_commit"
export SOURCE_DATE_EPOCH="$source_epoch"
unset LM_LICENSE_FILE MGLS_LICENSE_FILE QUARTUS_LICENSE_FILE || true

set +e
./scripts/build_core.sh 2>&1 | tee "$artifact_root/quartus.log"
build_status=${PIPESTATUS[0]}
set -e

output_dir="$work_root/repo/src/fpga/output_files"
if [[ -d "$output_dir" ]]; then
  mkdir "$artifact_root/output_files"
  cp -a "$output_dir/." "$artifact_root/output_files/"
fi

if (( build_status != 0 )); then
  echo "Quartus compile failed with status $build_status; partial reports were preserved" >&2
  exit "$build_status"
fi

for required in ap_core.rbf ap_core.fit.rpt ap_core.asm.rpt ap_core.sta.rpt ap_core.flow.rpt; do
  test -s "$artifact_root/output_files/$required" || {
    echo "successful flow did not produce required fit/timing artifact: $required" >&2
    exit 78
  }
done

cp src/fpga/apf/build_id.mif "$artifact_root/build_id.mif"
/opt/intelFPGA/quartus/bin/quartus_sh --version > "$artifact_root/toolchain-version.txt"
sha256sum "$artifact_root/output_files/ap_core.rbf" > "$artifact_root/ap_core.rbf.sha256"
printf '%s\n' \
  "source_commit=$source_commit" \
  "source_date_epoch=$source_epoch" \
  "platform=linux/amd64" \
  "quartus=21.1.1.850 Lite" \
  "device=5CEBA4F23C8" \
  > "$artifact_root/build-metadata.txt"

echo "Quartus fit/timing artifacts copied to $artifact_root"
