# Migrating Pocket data to the Swan Song core ID

Swan Song uses the independent Pocket core ID
`RegionallyFamous.SwanSong`. Pocket stores some user data below a core-ID
namespace, so an existing `agg23.WonderSwan` installation does not
automatically expose that data to Swan Song.

The offline helper [`scripts/migrate_swan_song_namespace.py`](scripts/migrate_swan_song_namespace.py)
copies only the small, understood subset that is safe to migrate:

- `/Saves/wonderswan/agg23.WonderSwan/mono.eeprom` to the new core namespace,
  only when it is exactly 128 bytes;
- `/Saves/wonderswan/agg23.WonderSwan/color.eeprom`, only when it is exactly
  2,048 bytes; and
- valid `.json` files recursively below `/Settings/agg23.WonderSwan` and
  `/Presets/agg23.WonderSwan`, preserving their relative paths below
  `/Settings/RegionallyFamous.SwanSong` and
  `/Presets/RegionallyFamous.SwanSong`.

The helper does **not** copy or inspect Memories, ROMs, BIOS files, common
cartridge saves, or any other application directory. Swan Song's cartridge
slot is now core-specific, so legacy `/Saves/wonderswan/common` files require
the separate ROM-aware [cartridge-save migration helper](CARTRIDGE_SAVE_MIGRATION.md).
Do not duplicate those saves by hand: inherited and canonical layouts can
differ. Both helpers download nothing.

## Run a read-only plan first

Mount the Pocket SD card on the Mac, identify its root below `/Volumes`, and
run:

```sh
python3 scripts/migrate_swan_song_namespace.py \
  --sd-root "/Volumes/POCKET"
```

This is the default and writes nothing. It validates both source EEPROM sizes,
walks only the two old JSON namespaces, rejects malformed or excessive JSON,
rejects symlinks and special files, and classifies every destination as either
`COPY` or byte-for-byte `IDENTICAL`. Review the complete printed plan before
continuing.

The JSON walk is capped at 16 directory levels, 8,192 entries per namespace,
4,096 JSON files and 16 MiB across both namespaces, and 1 MiB per JSON file.
JSON must be UTF-8 with an object at the top level; duplicate fields and
non-standard numeric constants are rejected. Regular non-JSON files are
ignored rather than copied. macOS AppleDouble `._*` entries and `.DS_Store`
are treated as filesystem metadata and ignored even when a sidecar name ends
in `.json`; malformed ordinary JSON remains a hard failure.

Both EEPROM source files are required. If the old core never created one,
launch that installed core normally first or initialize the missing console
profile there; do not synthesize an EEPROM file with this tool.

## Apply the reviewed plan

Rerun the same command with the explicit mutation flag:

```sh
python3 scripts/migrate_swan_song_namespace.py \
  --sd-root "/Volumes/POCKET" \
  --apply
```

The helper revalidates the complete source and destination inventory before
writing. New files are first completed and flushed under a temporary name in
the destination directory, then installed with the operating system's atomic
no-replace primitive (or an atomic hard-link fallback), reread, and
byte-verified. If the mounted filesystem offers neither guarantee, the helper
refuses to write. Existing identical destinations are left untouched. If any
destination differs, the complete preflight fails before the helper copies a
file; there is no overwrite or force mode.

### Current macOS exFAT boundary

The read-only plan has been exercised on a disposable, natively mounted exFAT
image on macOS 26.5.2 and correctly filtered the AppleDouble entries created by
that filesystem. The same filesystem returned `ENOTSUP` for both exclusive
rename and atomic swap, and exFAT does not provide the hard-link fallback.
Consequently, `--apply` deliberately fails closed on that tested Mac/exFAT
combination before publishing a destination file. Do not work around this by
adding an overwrite flag or by deleting the old namespace.

If migration is needed on an exFAT Pocket card today, keep the Pocket powered
off, make a complete backup, and use a host/filesystem combination on which
the helper's atomic no-replace install succeeds. Rerun the read-only plan
afterward: a correctly migrated card reports every intended destination as
`IDENTICAL`. A VM is useful only if the physical SD is passed through to it;
the exact guest exFAT implementation must still prove the operation rather
than being assumed safe.

Every operation is a copy. The old `agg23.WonderSwan` data is never renamed,
moved, or deleted, so it remains available to the upstream core. If a later
write fails while the process is running, the uninstalled temporary name is
removed; already completed copies remain valid and the source remains intact.
A sudden power loss can still lose or corrupt recently written removable-media
data despite successful system calls, so rerun the read-only plan and compare
the printed source/destination hashes before hardware use.

Finally, eject the SD card cleanly and confirm the console owner data and the
desired Pocket settings/presets on hardware. This helper only migrates files;
it does not claim that Pocket firmware applies every historical setting in the
same way to a newly named core.
