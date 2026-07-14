# Install Swan Song

> **There is no verified Swan Song release to install yet.** Do not treat a
> development ZIP, source checkout, or third-party repost as a release. Wait
> for an explicitly verified package on the official [Swan Song Releases
> page](https://github.com/RegionallyFamous/swan-song/releases).

This page describes the intended installation flow once the first verified
release is published.

## What you will need

- an Analogue Pocket with the official firmware required by that Swan Song
  release (the current development acceptance target is firmware 2.6.0);
- a backed-up Pocket SD card;
- the verified Swan Song APF ZIP from the official Releases page;
- your own legally obtained original WonderSwan and WonderSwan Color BIOS
  dumps; and
- your own legally obtained `.ws` and `.wsc` game images.

Normal players will not need Quartus, Docker, Verilator, a virtual machine, or
a cloud server. Those are developer tools.

Pocket firmware must come from the official [Analogue Pocket support
page](https://www.analogue.co/support/pocket), not from a core ZIP or a mirror.

## Install the core

1. Power off the Pocket and make a complete backup of the SD card.
2. Download the verified Swan Song ZIP from the official Releases page.
3. Extract the ZIP. Merge its `Assets`, `Cores`, and `Platforms` folders into
   the matching folders at the root of the SD card.
4. Eject the SD card cleanly, return it to the Pocket, and start Swan Song from
   **openFPGA**.

On macOS, do not let Finder replace an existing top-level folder with the
folder from the ZIP. A replacement can remove unrelated cores or personal
files. Once a release is authorized, the official source commit includes a
read-only-first staging command that verifies the published ZIP SHA-256,
published provenance SHA-256, version, source commit, exact release provenance,
and release-policy authorization before offering an explicit merge. The command
currently refuses installation because no release is authorized. See the [Pocket SD staging
guide](https://github.com/RegionallyFamous/swan-song/blob/main/POCKET_SD_STAGING.md).

## Add the required BIOS files

Swan Song does not provide or download firmware. Place your own dumps at these
exact paths on the SD card:

| System | Path | Exact size | MD5 |
| --- | --- | ---: | --- |
| WonderSwan | `/Assets/wonderswan/common/bw.rom` | 4,096 bytes | `54B915694731CC22E07D3FB8A00EE2DB` |
| WonderSwan Color | `/Assets/wonderswan/common/color.rom` | 8,192 bytes | `880893BD5A7D53FFF826BD76A83D566E` |

Both files are required even if you initially plan to play only one model.
These checksums help identify the expected files; they are not download links.

## Add games

Place legally obtained `.ws` and `.wsc` images anywhere below:

```text
/Assets/wonderswan/common/
```

Subfolders are welcome. Swan Song does not need a title database and does not
catalogue your collection.

## Side-by-side installation

Swan Song installs as `/Cores/RegionallyFamous.SwanSong`, so it can remain next
to `/Cores/agg23.WonderSwan`. Do not rename one core folder into the other.
Pocket derives settings and console-data paths from the core identity.

Games and BIOS files remain in the shared `wonderswan/common` asset folder.
Cartridge saves use Swan Song's core-specific namespace. Older shared saves do
not appear automatically; back up the card and use the ROM-aware migration
helper rather than copying them by hand. See [Saves and
Migration](https://github.com/RegionallyFamous/swan-song/wiki/Saves-and-Migration).

## Mac staging and development packages

The repository includes a read-only-first Mac staging workflow. Its development
mode remains tied to the exact checkout and cannot make an unverified build
safe for ordinary use. Its separate release mode requires trusted published
identity and refuses the current unauthorized policy. See the [Pocket SD staging
guide](https://github.com/RegionallyFamous/swan-song/blob/main/POCKET_SD_STAGING.md)
and [Build and
Test](https://github.com/RegionallyFamous/swan-song/wiki/Build-and-Test) only if
you are helping test the project.
