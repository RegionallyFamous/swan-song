# Stage Swan Song on an Analogue Pocket SD card

`scripts/stage_pocket_sd.py` validates a Swan Song package and prepares an SD
tree without reading game contents. Dry-run is the default; writing requires
`--apply`, and a target below macOS `/Volumes` additionally requires
`--allow-volume`.

Swan Song uses its built-in open IPL. It does not require, import, copy, or
upload external BIOS files. Add only game images that you are legally entitled
to use.

## Development package

Create a local staging directory, then validate the package and its provenance:

```bash
mkdir -p /tmp/swansong-pocket
python3 scripts/stage_pocket_sd.py \
  --staging-dir /tmp/swansong-pocket \
  --package /path/to/RegionallyFamous.SwanSong.zip
```

The default provenance path is `<package>.provenance.json`. Review the complete
plan, then rerun with `--apply`. Merge the resulting `Assets`, `Cores`, and
`Platforms` folders into the SD root; do not use Finder's Replace operation.

## Verified release

Release verification also requires trusted published identities:

```bash
python3 scripts/stage_pocket_sd.py \
  --staging-dir /tmp/swansong-pocket \
  --package /path/to/RegionallyFamous.SwanSong.zip \
  --verify-release \
  --expected-package-sha256 <published-zip-sha256> \
  --expected-provenance-sha256 <published-provenance-sha256> \
  --expected-version <published-version> \
  --expected-source-commit <published-40-hex-commit>
```

The checked-in release policy must authorize that exact release. A package,
provenance, policy, version, commit, licensing, or installed-payload mismatch
stops staging before any write.

## Write directly to a mounted SD card

After reviewing the dry-run plan:

```bash
python3 scripts/stage_pocket_sd.py \
  --staging-dir "/Volumes/POCKET" \
  --package /path/to/RegionallyFamous.SwanSong.zip \
  --apply \
  --allow-volume
```

The stager writes only validated managed files, preserves unrelated files, and
uses rollback-checked atomic publication. It never removes games or saves.
Back up the SD card before writing.

Place `.ws` and `.wsc` games under:

```text
/Assets/wonderswan/common/
```

Swan Song uses a core-specific cartridge-save namespace. Run
`scripts/swan_song_doctor.py` after staging; if it reports legacy shared saves,
follow [`CARTRIDGE_SAVE_MIGRATION.md`](CARTRIDGE_SAVE_MIGRATION.md) rather than
copying save files by hand.
