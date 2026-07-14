# Safely migrate cartridge saves into Swan Song

Swan Song uses Pocket's core-specific, slot-0-cloned save namespace:

```text
/Assets/wonderswan/common/Folder/Game.wsc
/Saves/wonderswan/RegionallyFamous.SwanSong/Folder/Game.sav
```

Older WonderSwan cores may instead have written the same game beneath
`/Saves/wonderswan/common/`. Do not copy those files blindly. Older cores used
different save sizes for some cartridge footer types; a same-named file can be
valid for the older core and invalid for Swan Song.

Make a complete SD backup, stop Pocket from accessing the card, and preview a
single personally owned game first:

```sh
python3 scripts/migrate_cartridge_save_namespace.py \
  --sd-root "/Volumes/POCKET" \
  --select "Folder/Game.wsc"
```

The selected path is relative to `/Assets/wonderswan/common`. Repeat
`--select` for more games, or use the bounded `--all` scan:

```sh
python3 scripts/migrate_cartridge_save_namespace.py \
  --sd-root "/Volumes/POCKET" \
  --all
```

Both commands are read-only. The helper reads each selected ROM only to
validate its final WonderSwan footer and checksum and to obtain its save type
and RTC flag. It then maps the ROM to the same-relative `.sav`, accepts only a
canonical or explicitly recognized inherited layout, and prints the exact
copy/conversion plan and output SHA-256. It has no title database and uploads
nothing.

Recognized inherited layouts are deliberately narrow:

- type `01`: an 8,204-byte inherited file expands the 8 KiB payload to the
  corrected 32 KiB capacity; the 12-byte trailer is retained only for an RTC
  ROM;
- types `10` and `50`: a 2,060-byte inherited file is reduced to its exact
  128- or 1,024-byte EEPROM payload, with the trailer retained only for RTC;
- type `20` and SRAM types `02`–`05`: a non-RTC inherited file may lose one
  trailing 12-byte agg trailer only when that trailer starts with `RT`; and
- an already canonical file is copied exactly. No-save titles and titles with
  no shared save are reported and skipped.

Wrong lengths, invalid ROM checksums, unsupported footer types, ambiguous
`.ws`/`.wsc` stems, case collisions, symlinks, differing destinations, and
unrecognized trailers fail the complete plan. Non-`.sav` files are untouched.

After reviewing the plan, apply only with the explicit flag:

```sh
python3 scripts/migrate_cartridge_save_namespace.py \
  --sd-root "/Volumes/POCKET" \
  --select "Folder/Game.wsc" \
  --apply
```

The source is never moved, renamed, deleted, or modified. A destination is
atomically created without replacement; an identical destination is
idempotent, while a different file stops the plan. If the mounted filesystem
cannot provide atomic no-replace publication, apply fails closed. Never work
around that protection by deleting the destination or adding an overwrite.

Eject cleanly, launch Swan Song, confirm the save in game, quit normally, and
relaunch before removing any backup or shared source. This workflow preserves
files safely; final Pocket persistence remains a physical release gate.
