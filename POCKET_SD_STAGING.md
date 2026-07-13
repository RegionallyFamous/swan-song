# Safe Mac-side Pocket SD staging

This workflow validates a Swan Song **development** package and builds a local
Pocket-shaped directory tree without touching a mounted SD card by default. It
never downloads or bundles a BIOS or game image.

Analogue documents a core ZIP as a snapshot of the Pocket SD filesystem that
is extracted at the SD root. Core definitions belong under
`/Cores/Author.Core`, shared platform assets under
`/Assets/<platform>/common`, and platform metadata/art under `/Platforms`.
Those rules come from Analogue's current [SD directory](https://www.analogue.co/developer/docs/directories-and-sd-folder-structure)
and [core packaging](https://www.analogue.co/developer/docs/packaging-a-core)
documentation. Swan Song therefore manages only:

- `Assets/wonderswan/common/bw.rom`
- `Assets/wonderswan/common/color.rom`
- the package's `Cores/agg23.WonderSwan` files
- `Platforms/wonderswan.json` and `Platforms/_images/wonderswan.bin`

Unrelated files and directories are neither deleted nor rewritten.

## Prerequisites

Build a development package with the repository's normal package command. It
must have its adjacent `.provenance.json` file. Release packages are
deliberately rejected by this staging tool.

Provide your own legally obtained BIOS dumps:

- `bw.rom`: exactly 4,096 bytes
- `color.rom`: exactly 8,192 bytes

The paths may have any source filename; the staged destination names are fixed
by the checked-in APF data slots. The script verifies their sizes and reports
SHA-256 hashes for the operator's log. It does not search for, download,
extract, or identify BIOS content on the user's behalf.

Create an ordinary local directory outside `/Volumes`:

```sh
mkdir -p "$HOME/Desktop/Swan-Song-Pocket-stage"
```

## Read-only validation first

```sh
python3 scripts/stage_pocket_sd.py \
  --staging-dir "$HOME/Desktop/Swan-Song-Pocket-stage" \
  --package "/path/to/swan-song-development.zip" \
  --bw-bios "/path/to/your/bw.rom" \
  --color-bios "/path/to/your/color.rom"
```

Without `--apply`, the command performs no writes. It validates:

- the ZIP and adjacent package provenance SHA-256/file inventory;
- development—not release—provenance;
- safe relative ZIP paths, permitted top-level directories, entry count and
  expanded-size limits, and the absence of encrypted entries, symlinks,
  special files, traversal, duplicates, and case collisions;
- the full APF source definition using the repository's existing strict
  package validator;
- the exact current checkout's static definitions, art, core identity,
  platform identity, repository identity, generated-bitstream name, and
  Chip32 name, rejecting an older or foreign development package;
- the required BIOS data-slot contract and the two user-supplied file sizes;
- every managed destination before proposing a merge, including symlink and
  case-collision checks.

The current `core.json` and `data.json` contracts are documented by Analogue at
[`core.json`](https://www.analogue.co/developer/docs/core-definition-files/core-json)
and [`data.json`](https://www.analogue.co/developer/docs/core-definition-files/data-json).

## Apply to the local staging tree

After reviewing the summary, repeat the same command with `--apply`:

```sh
python3 scripts/stage_pocket_sd.py \
  --staging-dir "$HOME/Desktop/Swan-Song-Pocket-stage" \
  --package "/path/to/swan-song-development.zip" \
  --bw-bios "/path/to/your/bw.rom" \
  --color-bios "/path/to/your/color.rom" \
  --apply
```

Writes use same-directory temporary files followed by atomic replacement. The
entire destination plan is checked before the first write and each managed
path is checked again immediately before use. Existing identical files are
left alone. Existing managed files are replaced; unrelated content is
preserved. Nothing is pruned.

Add only personally and legally obtained `.ws`/`.wsc` images beneath the local
`Assets/wonderswan/common/` tree. Inspect the complete staging directory, then
merge its `Assets`, `Cores`, and `Platforms` directories into the SD root.
Avoid Finder's **Replace** action because it can replace a whole destination
folder instead of merging its contents.

## Actual-SD safety boundary

On macOS, removable filesystems are normally mounted below `/Volumes`. A
read-only validation may inspect such a selected target, but an apply below
`/Volumes` fails unless **both** `--apply` and `--allow-volume` are present.
This extra flag is an operator acknowledgement, not automatic SD detection:
internal and network volumes can also appear there, and an unusually mounted
SD can appear elsewhere.

Direct-SD writes are intentionally not the default or recommended first run.
If explicitly used, verify the volume name and keep a backup before running:

```sh
python3 scripts/stage_pocket_sd.py \
  --staging-dir "/Volumes/POCKET" \
  --package "/path/to/swan-song-development.zip" \
  --bw-bios "/path/to/your/bw.rom" \
  --color-bios "/path/to/your/color.rom" \
  --apply --allow-volume
```

The tool cannot make a direct write risk-free. Power loss, media failure, a
mistyped mount point, or an external process racing the validated tree can
still cause damage. It deliberately does not format, mount, unmount, eject,
publish, download assets, alter firmware, delete stale cores, or release a
package. Eject the card cleanly after the copy and perform Pocket hardware
validation separately.
