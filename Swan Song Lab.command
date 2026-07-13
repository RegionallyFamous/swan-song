#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

if (( $# )); then
  exec /usr/bin/env python3 scripts/swan_song_lab.py "$@"
fi

if [[ -f .swan-song-lab/state.json ]]; then
  exec /usr/bin/env python3 scripts/swan_song_lab.py status
fi

exec /usr/bin/env python3 scripts/swan_song_lab.py launch
