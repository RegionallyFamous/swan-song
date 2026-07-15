#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QUARTUS_SH="${QUARTUS_SH:-quartus_sh}"
ARTIFACT_ROOT=""

usage() {
  echo "Usage: scripts/build_core.sh [--artifacts EMPTY-DIRECTORY]" >&2
}

if (( $# == 2 )) && [[ "$1" == --artifacts ]]; then
  ARTIFACT_ROOT="$2"
elif (( $# != 0 )); then
  usage
  exit 64
fi

command -v "$QUARTUS_SH" >/dev/null || {
  echo "quartus_sh not found; install Quartus Prime Lite 21.1.1 on Linux or Windows" >&2
  exit 127
}
QUARTUS_STA="${QUARTUS_STA:-$(dirname "$(command -v "$QUARTUS_SH")")/quartus_sta}"
command -v "$QUARTUS_STA" >/dev/null || {
  echo "quartus_sta not found beside quartus_sh; install Quartus Prime Lite 21.1.1" >&2
  exit 127
}

required_outputs=(
  ap_core.rbf
  ap_core.map.rpt
  ap_core.fit.rpt
  ap_core.asm.rpt
  ap_core.sta.rpt
  ap_core.flow.rpt
)

resolve_source_identity() {
  local git_commit git_epoch exclude_mif
  if [[ -n "${SWANSONG_SOURCE_COMMIT:-}" || -n "${SOURCE_DATE_EPOCH:-}" ]]; then
    [[ -n "${SWANSONG_SOURCE_COMMIT:-}" && -n "${SOURCE_DATE_EPOCH:-}" ]] || {
      echo "SWANSONG_SOURCE_COMMIT and SOURCE_DATE_EPOCH must be supplied together" >&2
      return 76
    }
  else
    [[ -d "$ROOT/.git" ]] || {
      echo "evidence output requires Git identity or both source identity variables" >&2
      return 76
    }
    exclude_mif=':(exclude)src/fpga/apf/build_id.mif'
    git -C "$ROOT" diff --quiet -- . "$exclude_mif" || {
      echo "tracked source has unstaged changes; refusing source-bound evidence" >&2
      return 74
    }
    git -C "$ROOT" diff --cached --quiet -- . "$exclude_mif" || {
      echo "tracked source has staged changes; refusing source-bound evidence" >&2
      return 75
    }
    SWANSONG_SOURCE_COMMIT="$(git -C "$ROOT" rev-parse --verify HEAD)"
    SOURCE_DATE_EPOCH="$(git -C "$ROOT" show -s --format=%ct "$SWANSONG_SOURCE_COMMIT")"
    export SWANSONG_SOURCE_COMMIT SOURCE_DATE_EPOCH
  fi

  case "$SWANSONG_SOURCE_COMMIT" in
    (????????????????????????????????????????)
      [[ "$SWANSONG_SOURCE_COMMIT" != *[!0-9a-f]* ]] || {
        echo "invalid Git source commit: $SWANSONG_SOURCE_COMMIT" >&2
        return 76
      }
      ;;
    (*) echo "invalid Git source commit: $SWANSONG_SOURCE_COMMIT" >&2; return 76 ;;
  esac
  case "$SOURCE_DATE_EPOCH" in
    (*[!0-9]*|'') echo "invalid Git source epoch: $SOURCE_DATE_EPOCH" >&2; return 77 ;;
  esac

  if [[ -d "$ROOT/.git" ]]; then
    git_commit="$(git -C "$ROOT" rev-parse --verify HEAD)"
    git_epoch="$(git -C "$ROOT" show -s --format=%ct "$git_commit")"
    [[ "$git_commit" == "$SWANSONG_SOURCE_COMMIT" ]] || {
      echo "SWANSONG_SOURCE_COMMIT does not identify the checked-out HEAD" >&2
      return 76
    }
    [[ "$git_epoch" == "$SOURCE_DATE_EPOCH" ]] || {
      echo "SOURCE_DATE_EPOCH does not match the source commit" >&2
      return 77
    }
  fi
}

resolve_build_identity() {
  SWANSONG_BUILD_CLASS="${SWANSONG_BUILD_CLASS:-development}"
  export SWANSONG_BUILD_CLASS
  if [[ "$SWANSONG_BUILD_CLASS" == development ]]; then
    for name in \
      SWANSONG_WORKFLOW_REPOSITORY SWANSONG_WORKFLOW_PATH \
      SWANSONG_WORKFLOW_SHA SWANSONG_WORKFLOW_RUN_ID \
      SWANSONG_WORKFLOW_RUN_ATTEMPT SWANSONG_WORKFLOW_JOB \
      SWANSONG_BUILD_JOB_NONCE; do
      [[ -z "${!name:-}" ]] || {
        echo "development build refuses GitHub workflow identity: $name" >&2
        return 76
      }
    done
    return 0
  fi
  [[ "$SWANSONG_BUILD_CLASS" == candidate ]] || {
    echo "SWANSONG_BUILD_CLASS must be development or candidate" >&2
    return 76
  }
  [[ "${SWANSONG_WORKFLOW_REPOSITORY:-}" == RegionallyFamous/swan-song ]] || {
    echo "invalid or missing SWANSONG_WORKFLOW_REPOSITORY" >&2
    return 76
  }
  [[ "${SWANSONG_WORKFLOW_PATH:-}" == .github/workflows/quartus-fit.yml ]] || {
    echo "invalid or missing SWANSONG_WORKFLOW_PATH" >&2
    return 76
  }
  [[ "${SWANSONG_WORKFLOW_SHA:-}" == "$SWANSONG_SOURCE_COMMIT" ]] || {
    echo "SWANSONG_WORKFLOW_SHA does not identify the build source commit" >&2
    return 76
  }
  case "${SWANSONG_WORKFLOW_RUN_ID:-}" in
    ([1-9]*)
      [[ "$SWANSONG_WORKFLOW_RUN_ID" != *[!0-9]* ]] || {
        echo "invalid SWANSONG_WORKFLOW_RUN_ID" >&2
        return 76
      }
      ;;
    (*) echo "invalid or missing SWANSONG_WORKFLOW_RUN_ID" >&2; return 76 ;;
  esac
  case "${SWANSONG_WORKFLOW_RUN_ATTEMPT:-}" in
    ([1-9]*)
      [[ "$SWANSONG_WORKFLOW_RUN_ATTEMPT" != *[!0-9]* ]] || {
        echo "invalid SWANSONG_WORKFLOW_RUN_ATTEMPT" >&2
        return 76
      }
      ;;
    (*) echo "invalid or missing SWANSONG_WORKFLOW_RUN_ATTEMPT" >&2; return 76 ;;
  esac
  [[ "${SWANSONG_WORKFLOW_JOB:-}" == fit ]] || {
    echo "invalid or missing SWANSONG_WORKFLOW_JOB" >&2
    return 76
  }
  case "${SWANSONG_BUILD_JOB_NONCE:-}" in
    (????????????????????????????????)
      [[ "$SWANSONG_BUILD_JOB_NONCE" != *[!0-9a-f]* ]] || {
        echo "invalid SWANSONG_BUILD_JOB_NONCE" >&2
        return 76
      }
      ;;
    (*) echo "invalid or missing SWANSONG_BUILD_JOB_NONCE" >&2; return 76 ;;
  esac
}

prepare_artifact_root() {
  mkdir -p "$ARTIFACT_ROOT"
  [[ -d "$ARTIFACT_ROOT" && ! -L "$ARTIFACT_ROOT" ]] || {
    echo "artifact path must be a nonsymlink directory: $ARTIFACT_ROOT" >&2
    return 73
  }
  ARTIFACT_ROOT="$(cd "$ARTIFACT_ROOT" && pwd -P)"
  case "$ARTIFACT_ROOT/" in
    ("$ROOT/src/fpga/"*)
      echo "artifact directory must be outside src/fpga: $ARTIFACT_ROOT" >&2
      return 73
      ;;
  esac
  if find "$ARTIFACT_ROOT" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    echo "artifact directory must be empty: $ARTIFACT_ROOT" >&2
    return 73
  fi
  [[ "$(uname -s)" == Linux && "$(uname -m)" =~ ^(x86_64|amd64)$ ]] || {
    echo "source-bound Quartus evidence requires Linux/amd64" >&2
    return 76
  }
  resolve_source_identity
  resolve_build_identity
}

run_quartus() {
  local output
  cd "$ROOT/src/fpga"
  # Remove every allowlisted result first. A failed current run must never copy
  # a report or bitstream left by an earlier compile into its evidence tree.
  for output in "${required_outputs[@]}"; do
    rm -f "output_files/$output"
  done

  cleanup_failed_build() {
    local status=$?
    if (( status != 0 )); then
      rm -f output_files/ap_core.rbf
    fi
    return "$status"
  }
  trap cleanup_failed_build EXIT

  "$QUARTUS_SH" --flow compile ap_core || return $?

  # Append bounded endpoint diagnostics and strict post-fit timing gates to the
  # native STA report. A bitstream without this signoff evidence is discarded.
  "$QUARTUS_STA" -t "$ROOT/scripts/quartus_signoff_paths.tcl" || return $?

  test -s output_files/ap_core.rbf || {
    echo "Quartus completed without output_files/ap_core.rbf" >&2
    return 1
  }

  trap - EXIT
}

copy_partial_outputs() {
  local output
  mkdir -p "$ARTIFACT_ROOT/output_files" || return 83
  for output in "${required_outputs[@]}"; do
    if [[ -f "$ROOT/src/fpga/output_files/$output" && ! -L "$ROOT/src/fpga/output_files/$output" ]]; then
      cp "$ROOT/src/fpga/output_files/$output" "$ARTIFACT_ROOT/output_files/$output" \
        || return 83
    fi
  done
}

write_success_evidence() {
  local output rbf_digest
  local -a metadata
  for output in "${required_outputs[@]}"; do
    test -s "$ARTIFACT_ROOT/output_files/$output" || {
      echo "successful flow did not produce required compilation artifact: $output" >&2
      return 78
    }
  done
  test -s "$ROOT/src/fpga/apf/build_id.mif" || {
    echo "successful flow did not produce src/fpga/apf/build_id.mif" >&2
    return 78
  }

  cp "$ROOT/src/fpga/apf/build_id.mif" "$ARTIFACT_ROOT/build_id.mif" \
    || return 78
  "$QUARTUS_SH" --version > "$ARTIFACT_ROOT/toolchain-version.txt" \
    || return 78
  rbf_digest="$(sha256sum "$ARTIFACT_ROOT/output_files/ap_core.rbf" | awk '{print $1}')" \
    || return 78
  [[ "$rbf_digest" =~ ^[0-9a-f]{64}$ ]] || {
    echo "could not hash output_files/ap_core.rbf" >&2
    return 78
  }
  printf '%s  /artifacts/output_files/ap_core.rbf\n' "$rbf_digest" \
    > "$ARTIFACT_ROOT/ap_core.rbf.sha256" || return 78
  metadata=(
    "source_commit=$SWANSONG_SOURCE_COMMIT"
    "source_date_epoch=$SOURCE_DATE_EPOCH"
  )
  if [[ "$SWANSONG_BUILD_CLASS" == candidate ]]; then
    metadata+=(
      "workflow_repository=$SWANSONG_WORKFLOW_REPOSITORY"
      "workflow_path=$SWANSONG_WORKFLOW_PATH"
      "workflow_sha=$SWANSONG_WORKFLOW_SHA"
      "workflow_run_id=$SWANSONG_WORKFLOW_RUN_ID"
      "workflow_run_attempt=$SWANSONG_WORKFLOW_RUN_ATTEMPT"
      "workflow_job=$SWANSONG_WORKFLOW_JOB"
      "workflow_job_nonce=$SWANSONG_BUILD_JOB_NONCE"
    )
  else
    metadata+=("build_class=development")
  fi
  metadata+=(
    "platform=linux/amd64"
    "quartus=21.1.1.850 Lite"
    "device=5CEBA4F23C8"
  )
  printf '%s\n' "${metadata[@]}" > "$ARTIFACT_ROOT/build-metadata.txt" \
    || return 78
}

if [[ -z "$ARTIFACT_ROOT" ]]; then
  run_quartus
  echo "$ROOT/src/fpga/output_files/ap_core.rbf"
  exit 0
fi

prepare_artifact_root
set +e
run_quartus 2>&1 | tee "$ARTIFACT_ROOT/quartus.log"
pipeline_status=("${PIPESTATUS[@]}")
set -e
if (( ${#pipeline_status[@]} != 2 )); then
  echo "could not capture the Quartus/log pipeline status" >&2
  rm -f "$ROOT/src/fpga/output_files/ap_core.rbf"
  exit 84
fi
build_status=${pipeline_status[0]}
log_status=${pipeline_status[1]}
set +e
copy_partial_outputs
copy_status=$?
set -e
if (( copy_status != 0 )); then
  echo "could not copy the current Quartus reports into the artifact directory" >&2
  rm -f "$ROOT/src/fpga/output_files/ap_core.rbf" "$ARTIFACT_ROOT/output_files/ap_core.rbf"
  exit "$copy_status"
fi
if (( log_status != 0 )); then
  echo "could not write the complete Quartus log (tee status $log_status)" >&2
  rm -f "$ROOT/src/fpga/output_files/ap_core.rbf" "$ARTIFACT_ROOT/output_files/ap_core.rbf"
  exit 83
fi
if (( build_status != 0 )); then
  echo "Quartus compile failed with status $build_status; partial reports were preserved" >&2
  exit "$build_status"
fi
set +e
write_success_evidence
evidence_status=$?
set -e
if (( evidence_status != 0 )); then
  rm -f "$ROOT/src/fpga/output_files/ap_core.rbf" "$ARTIFACT_ROOT/output_files/ap_core.rbf"
  exit "$evidence_status"
fi
echo "Quartus fit/timing evidence written to $ARTIFACT_ROOT"
