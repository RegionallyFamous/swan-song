# Saves and Migration

> Swan Song has no verified release yet. Exact save sizing and lifecycle are
> covered by automated tests, but final quit, title-switch, power-cycle,
> Pocket, and Dock behavior remains a physical release gate.

## Back up first

Before testing Swan Song or alternating between WonderSwan cores, copy the
complete Pocket SD card to a safe local folder. Do not experiment on the only
copy of a valued save.

## Three kinds of persistent data

Swan Song keeps different data in different places:

1. **Cartridge saves** belong to the selected game. Swan Song mirrors them
   below `/Saves/wonderswan/RegionallyFamous.SwanSong/`, preserving the path
   relative to `/Assets/wonderswan/common/`. The core-specific namespace keeps
   corrected Swan Song layouts from silently replacing an older core's save.
2. **Console owner data** belongs to the emulated machine. Swan Song uses
   `/Saves/wonderswan/RegionallyFamous.SwanSong/mono.eeprom` and
   `color.eeprom` for the mono and Color profiles.
3. **Core settings and per-game presets** live below the core-specific
   `/Settings/RegionallyFamous.SwanSong/` and
   `/Presets/RegionallyFamous.SwanSong/` namespaces.

The two console EEPROM files are separate from cartridge EEPROM or SRAM. An
ordinary reset does not intentionally erase either kind of data.

## Using Swan Song beside the upstream Pocket core

`RegionallyFamous.SwanSong` and `agg23.WonderSwan` can be installed side by
side. Their cartridge saves, console data, and settings are separate. A legacy
save below `/Saves/wonderswan/common/` is not loaded automatically by Swan
Song. Back up first and use the ROM-aware helper below; do not copy it by hand.

Do not rename one core directory to imitate the other. Do not manually copy a
Pocket Memories blob between the two identities.

## Migrating old development data

The repository includes a cautious helper for users who have Swan Song
development data under the historical `agg23.WonderSwan` namespace. It copies
only exact-size console EEPROM files and validated settings/preset JSON. It
does not copy ROMs, BIOS files, cartridge saves, or Memories.

Always run its read-only plan first:

```sh
python3 scripts/migrate_swan_song_namespace.py --sd-root "/Volumes/POCKET"
```

Review the complete plan before considering `--apply`. The helper never
overwrites a differing destination and leaves the old namespace in place.

The tested macOS 26.5.2 exFAT mount cannot provide the atomic no-replace
operation required by the helper, so apply deliberately fails safely there.
Do not work around that protection with manual deletion or an overwrite flag.
Use a host/filesystem combination that proves the required operation, then
rerun the read-only plan and verify every intended destination is identical.

Read the complete [core-ID migration
guide](https://github.com/RegionallyFamous/swansong-core/blob/main/CORE_ID_MIGRATION.md)
before applying anything.

## Legacy cartridge-save migration

Some older Pocket saves used padded or noncanonical lengths. Preview the
ROM-aware, no-clobber migration tool for one game before using `--all`:

```sh
python3 scripts/migrate_cartridge_save_namespace.py \
  --sd-root "/Volumes/POCKET" \
  --select "Folder/Game.wsc"
```

It validates the matching ROM footer/checksum and recognized save layout,
leaves the shared source unchanged, and never overwrites a destination. See
the complete [Cartridge Save Migration
guide](https://github.com/RegionallyFamous/swansong-core/blob/main/CARTRIDGE_SAVE_MIGRATION.md).

## Memories and Sleep/Wake

Pocket Memories and Sleep/Wake remain disabled. A future state format is being
designed and tested, but the live core does not claim safe save-state capture
or restoration. See [Compatibility and Current
Limits](https://github.com/RegionallyFamous/swansong-core/wiki/Compatibility-and-Current-Limits).
