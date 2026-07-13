#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
  echo "Quartus toolchain requires a linux/amd64 container" >&2
  exit 65
fi

quartus_sh_path=/opt/intelFPGA/quartus/bin/quartus_sh
test -x "$quartus_sh_path" || {
  echo "Quartus Shell is missing or not executable: $quartus_sh_path" >&2
  exit 66
}

version="$($quartus_sh_path --version)"
grep -Fq "Version 21.1.1 Build 850" <<<"$version" || {
  echo "unexpected Quartus version:" >&2
  echo "$version" >&2
  exit 67
}
grep -Fq "Lite Edition" <<<"$version" || {
  echo "Quartus installation is not the license-free Lite edition" >&2
  echo "$version" >&2
  exit 68
}

# A filename alone is not device support. Ask Quartus's device database to
# resolve the exact Analogue Pocket FPGA part and fail if it is not Cyclone V.
"$quartus_sh_path" -t /usr/local/share/swan-song/verify-toolchain.tcl

printf '%s\n' "$version"
printf '%s\n' "verified target 5CEBA4F23C8 (Cyclone V) on linux/amd64"
