# Troubleshooting and Bug Reports

> Swan Song has no verified release yet. If you are using a development build,
> say so clearly and include the exact source commit and FPGA artifact identity.

## Run Swan Song Doctor first

Swan Song Doctor can spot the most common SD-card setup problems before you
change files or open a bug report. With the Pocket SD card mounted, open
Terminal in a downloaded Swan Song source folder and run:

```bash
python3 scripts/swan_song_doctor.py --sd-root "/Volumes/POCKET"
```

Replace `/Volumes/POCKET` with the card's actual path. On macOS, you can drag
the mounted card from Finder into Terminal to paste its path.

By default the Doctor performs no content or namespace writes; filesystem reads
may still update access-time metadata. It checks the Swan Song installation,
required definitions, BIOS filenames and sizes, game and per-game settings
locations, player-visible icon/artwork files, older WonderSwan data, and unsafe
SD-card paths. It never uploads ROMs, BIOS files, or saves. By default it does
not open or hash game or BIOS contents; it locally enumerates filenames and
inspects file type and size. Game ROMs must be 64 KiB through 16 MiB in whole
64 KiB banks.

Add `--identify-bios` only if you want the Doctor to read the two exact-size
BIOS files and compare their local MD5 identifiers with those in the install
guide. This does not read game contents, upload anything, or reject an
unfamiliar same-size BIOS dump.

The result begins with `READY`, `READY WITH NOTES`, or `NEEDS ATTENTION`, and
each finding includes a suggested next step. The Doctor changes nothing unless
you deliberately select a repair and add `--apply`. Read the [complete Swan
Song Doctor
reference](https://github.com/RegionallyFamous/swan-song/blob/main/SWAN_SONG_DOCTOR.md)
before using an optional repair.

## Common setup problems

### Swan Song is not in an updater

There is no verified public release yet. An updater may install or restore the
upstream WonderSwan core instead. Use only a Swan Song release explicitly
published by Regionally Famous on the official [Releases
page](https://github.com/RegionallyFamous/swan-song/releases).

### Pocket asks for a BIOS

Confirm both files exist with the exact names and sizes:

- `/Assets/wonderswan/common/bw.rom` — 4,096 bytes
- `/Assets/wonderswan/common/color.rom` — 8,192 bytes

The project does not provide or locate these files.

### A game is not listed

Confirm it is an uncompressed regular `.ws` or `.wsc` file below
`/Assets/wonderswan/common/`. Archives, symlinks, `.pc2`, and files outside the
accepted size/bank boundary are not supported.

### A compact image is rejected

Non-power-of-two images need a valid final 16-byte WonderSwan footer and
checksum. Re-dump your own cartridge or correct your own homebrew build rather
than bypassing validation.

### Swan Song is not in Analogue Library

Third-party openFPGA cores do not have a documented public API for registering
first-party Library entries. Use openFPGA, optionally with Pocket's Startup
Action and host-owned Recent category.

### A save looks wrong

Stop using the affected file and back up the entire SD card before doing more.
Swan Song uses a core-specific cartridge-save namespace. If an older save is
still below `/Saves/wonderswan/common/`, do not hand-copy, trim, or rename it;
use the ROM-aware migration helper, which validates the game's footer and save
layout before an atomic no-overwrite copy.

## Before opening an issue

Collect:

- Swan Song release version, or exact Git commit and raw RBF/package hash;
- Pocket firmware version;
- Pocket or Dock, including controller type when relevant;
- selected System Type and all nondefault core settings;
- game orientation and whether the problem changes after a clean reset;
- whether it also occurs in the MiSTer WonderSwan core, if you can test that
  safely; and
- short, exact reproduction steps from launch to failure.

For visual or timing problems, a short Pocket/Dock capture can help. State
whether you also compared the same revision on original hardware; emulator
agreement alone does not establish the correct hardware result.

Open a [Swan Song GitHub
issue](https://github.com/RegionallyFamous/swan-song/issues) for Pocket
integration or Swan Song-specific behavior. Shared console-logic fixes should
be proposed upstream after verification, with a link back to the Swan Song
evidence.

## Protect private and copyrighted data

Never attach or upload a commercial ROM, BIOS, save, cartridge dump, private
corpus manifest, or cloud credential. Do not paste private filesystem paths or
DigitalOcean/GitHub state. Keep owner-computed commercial ROM identities in
private test evidence rather than posting them publicly, and always keep the
underlying file local.

Open and project-generated fixtures are preferred whenever they can reproduce
the problem. They make a report independently reviewable without redistributing
copyrighted data.
