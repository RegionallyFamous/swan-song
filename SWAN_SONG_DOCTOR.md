# Check your Pocket SD card with Swan Song Doctor

Swan Song Doctor checks whether Swan Song, games, per-game
settings, and older WonderSwan user-data folders are where Pocket expects them.
The normal command performs no content or namespace writes:

```bash
python3 scripts/swan_song_doctor.py --sd-root "/Volumes/POCKET"
```

Replace `/Volumes/POCKET` with your SD card's actual path. On macOS, drag the
mounted SD card from Finder into Terminal to paste its path.

The result starts with `READY`, `READY WITH NOTES`, or `NEEDS ATTENTION`.
Every problem includes a next step. `WARN` is something worth reviewing;
`ERROR` normally prevents Swan Song from working as intended. The doctor does
not change file contents, create names, or remove names unless you select a
specific repair and add `--apply`. As with other filesystem readers, opening
definition JSON may update access-time metadata on filesystems that track it.

## What it checks

- the `RegionallyFamous.SwanSong` folder and its identity in `core.json`;
- all required APF definitions, the referenced FPGA/Chip32 files, and the
  WonderSwan platform definition;
- the core menu icon, information text, and WonderSwan platform artwork;
- `.ws` and `.wsc` games below `/Assets/wonderswan/common/`, from 64 KiB
  through 16 MiB in whole 64 KiB cartridge banks;
- per-game Interact and Input paths mirrored below `/Presets`;
- stale `agg23.WonderSwan` Settings, Presets, and console EEPROM locations;
- legacy shared `.sav` files that Swan Song's core-specific slot will not load;
- unsafe symlinks, special files, path escapes, and FAT/exFAT case collisions.

Swan Song uses its built-in open IPL and does not require external BIOS files.
Game contents are never opened or hashed in any mode. The Doctor locally enumerates filenames and
inspects ordinary-file status and byte size. Exact names may appear in
findings, and per-game preset paths necessarily mirror a game's folder and
stem. Nothing is uploaded.

## Optional repairs

Preview creation of default per-game settings without writing:

```bash
python3 scripts/swan_song_doctor.py \
  --sd-root "/Volumes/POCKET" \
  --fix-presets
```

After reviewing the complete plan, add `--apply`. The repair creates only
missing Interact/Input preset pairs. Both files are prepared before either is
published; a failed second publication rolls the first one back. Concurrently
created destinations are never overwritten. It does not replace an existing
preset, read a ROM, or modify `/Settings`.

Interact-only and Input-only overrides can be intentional, so the Doctor
reports them explicitly but does not guess that the other half is missing or
overwrite either file. If an older generator was interrupted, back up the
existing preset before deciding whether to regenerate it.

Preview safe copies from the older core's namespace:

```bash
python3 scripts/swan_song_doctor.py \
  --sd-root "/Volumes/POCKET" \
  --migrate-legacy
```

Again, add `--apply` only after reviewing the plan. Migration copies the old
fixed console EEPROMs and valid Settings/Presets JSON into Swan Song's
namespace. Sources stay in place. A different destination is never
overwritten. Shared cartridge saves remain outside this repair allowlist:
their layouts depend on the matching ROM footer. When the Doctor reports them,
make a backup and use the separate read-only-first
[`migrate_cartridge_save_namespace.py`](CARTRIDGE_SAVE_MIGRATION.md) helper.
Do not copy them by hand.

Some FAT/exFAT mounts do not provide an atomic no-overwrite operation. In that
case preset creation and legacy migration stop safely instead of weakening the
no-clobber rule.

Use `--json` for a machine-readable report. `--apply` by itself is rejected;
you must also choose `--fix-presets`, `--migrate-legacy`, or both. Any unsafe
path finding blocks all repairs.

## Why these paths are checked

Analogue documents core identity as `/Cores/AuthorName.CoreName`, platform
assets under `/Assets/<platform>/common`, and user saves as a mirrored `/Saves`
tree in its [SD directory guide](https://www.analogue.co/developer/docs/directories-and-sd-folder-structure).
The cartridge and persistent-save slots come from Swan Song's `data.json`,
following Analogue's [data-slot contract](https://www.analogue.co/developer/docs/core-definition-files/data-json).

For a game such as:

```text
/Assets/wonderswan/common/Folder/Game.wsc
```

Analogue's [Interact documentation](https://www.analogue.co/developer/docs/core-definition-files/interact-json)
and [Input documentation](https://www.analogue.co/developer/docs/core-definition-files/input-json)
define these per-game mirrors:

```text
/Presets/RegionallyFamous.SwanSong/Interact/wonderswan/common/Folder/Game.json
/Presets/RegionallyFamous.SwanSong/Input/wonderswan/common/Folder/Game.json
```

A per-game file replaces the core's default definition rather than merging
with it. That is why the doctor flags stale Interact presets that lack Swan
Song's current Control Layout setting.

Analogue's [core packaging guide](https://www.analogue.co/developer/docs/packaging-a-core)
describes a core ZIP as SD-root folders, not a folder that should replace the
whole card. Unknown Pocket-created top-level folders are therefore left alone.
