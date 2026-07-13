# Safe Mac-side Pocket SD staging

This workflow validates a Swan Song **development** package and builds a local
Pocket-shaped directory tree without touching a mounted SD card by default. It
never downloads or bundles a BIOS or game image. Swan Song is maintained by
Regionally Famous and the package identity is `RegionallyFamous.SwanSong`.

Analogue documents a core ZIP as a snapshot of the Pocket SD filesystem that
is extracted at the SD root. Core definitions belong under
`/Cores/Author.Core`, shared platform assets under
`/Assets/<platform>/common`, and platform metadata/art under `/Platforms`.
Those rules come from Analogue's current [SD directory](https://www.analogue.co/developer/docs/directories-and-sd-folder-structure)
and [core packaging](https://www.analogue.co/developer/docs/packaging-a-core)
documentation. Swan Song therefore manages only:

- `Assets/wonderswan/common/bw.rom`
- `Assets/wonderswan/common/color.rom`
- the package's `Cores/RegionallyFamous.SwanSong` files
- `Platforms/wonderswan.json` and `Platforms/_images/wonderswan.bin`

Unrelated files and directories are neither deleted nor rewritten.

## Prerequisites

For Pocket use, first install the current official
[Pocket firmware 2.6.0](https://www.analogue.co/support/pocket/firmware/2.6.0)
if it is not already installed. The firmware download is separate from Swan
Song and has published MD5 `d5be2c99e436081266810594117db496`.

Build a development package from a reviewed raw RBF. On a supported Quartus
host, `make package` runs the compile and creates `build/SwanSong.zip`. If the
RBF was already produced—for example by the Apple-Silicon Docker workflow—run:

```sh
./scripts/package_core.py \
  --rbf /absolute/path/to/ap_core.rbf \
  --output build/SwanSong.zip
```

The command also creates `build/SwanSong.zip.provenance.json`, which must stay
beside the ZIP. Release packages are deliberately rejected by this staging
tool. Apple-Silicon developers need Docker Desktop and the exact Quartus Linux
download documented in [`QUARTUS_MAC_DOCKER.md`](QUARTUS_MAC_DOCKER.md); normal
Pocket users installing a verified release need neither Quartus nor Docker.

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

## Existing upstream core and user-data namespaces

Staging `Cores/RegionallyFamous.SwanSong` does not replace or delete
`Cores/agg23.WonderSwan`; the two APF identities can be installed side by side.
The script intentionally performs no user-data migration. Platform-common ROMs
and BIOS files stay shared in `Assets/wonderswan/common`. Slot-11 cartridge
saves also stay shared in the mirrored `Saves/wonderswan/common/...` path, so
make a backup before using the same cartridge save with both cores.

Fixed console EEPROM, settings, presets, and Memories are core-ID scoped. If a
prior development installation stored data under `agg23.WonderSwan`, make a
complete SD backup, stop Pocket/core access, and use the read-only-first
[core-ID migration helper](CORE_ID_MIGRATION.md) to copy rather than move:

- exact-size `mono.eeprom` and `color.eeprom` files from
  `Saves/wonderswan/agg23.WonderSwan/` into
  `Saves/wonderswan/RegionallyFamous.SwanSong/`;
- every eligible, valid JSON file recursively from
  `Settings/agg23.WonderSwan/` into
  `Settings/RegionallyFamous.SwanSong/`; and
- every eligible, valid JSON file recursively from
  `Presets/agg23.WonderSwan/` into
  `Presets/RegionallyFamous.SwanSong/`.

The helper's read-only plan is tested on macOS-mounted exFAT and ignores
AppleDouble sidecars. Its no-clobber apply mode deliberately fails closed on
the tested macOS 26.5.2 exFAT implementation because that filesystem supplies
neither exclusive rename, atomic swap, nor hard links. Review
[`CORE_ID_MIGRATION.md`](CORE_ID_MIGRATION.md) before attempting a write; a VM
must receive the physical SD and prove its own exFAT primitive rather than
being assumed safer.

Refuse destination overwrites, keep the source copy, confirm the EEPROM sizes
are 128 and 2,048 bytes, and test the new core before removing anything. Do not
copy `Memories/Beta/agg23.WonderSwan` into the new namespace: Swan Song does
not advertise Memories and defines no cross-ID Memory migration. These
boundaries follow Analogue's
[SD directory rules](https://www.analogue.co/developer/docs/directories-and-sd-folder-structure)
and per-core [Interact persistence paths](https://www.analogue.co/developer/docs/core-definition-files/interact-json).

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
