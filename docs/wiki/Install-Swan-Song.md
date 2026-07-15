# Install Swan Song

> **There is no verified Swan Song release to install yet.** Do not treat a
> development ZIP, source checkout, or third-party repost as a release. Wait
> for an explicitly verified package on the official [Swan Song Releases
> page](https://github.com/RegionallyFamous/swan-song/releases).

Historical protected-main Quartus candidate `f0345ee4` exists for controlled
Pocket/Dock hardware QA, but it remains a tester-only development package.
Newer source changes require a fresh regression and two distinct signed Quartus
workflow executions with byte-identical RBF and build-ID outputs. That proves
two signed workflow runs, not two different physical build hosts. The earlier
successful build does not authorize public distribution or replace the hardware
acceptance run.

This page describes the intended installation flow once the first verified
release is published.

## What you will need

- an Analogue Pocket with the official firmware required by that Swan Song
  release (the current development acceptance target is firmware 2.6.0);
- a backed-up Pocket SD card;
- the verified Swan Song APF ZIP and `SHA256SUMS` from the official Releases
  page;
- `signed-quartus-provenance.tar` and `release-manifest.json` when independently
  checking the two signed build origins;
- your own legally obtained original WonderSwan and WonderSwan Color BIOS
  dumps; and
- your own legally obtained `.ws` and `.wsc` game images.

Normal players will not need Quartus, Docker, Verilator, a virtual machine, or
a cloud server. Those are developer tools.

Pocket firmware must come from the official [Analogue Pocket support
page](https://www.analogue.co/support/pocket), not from a core ZIP or a mirror.

The `framework.version_required` value in Swan Song's `core.json` makes
Analogue OS 2.3 the minimum firmware that may load the core. That loader
minimum is not yet a promise that every 2.3-era host behavior is supported.
The first release's evidence-backed support floor remains an owner decision;
development hardware acceptance targets and recommends Analogue OS 2.6.0.
The verified release notes will state the final supported version.

## Install the core

1. Power off the Pocket and make a complete backup of the SD card.
2. Download the verified Swan Song ZIP and verify it against the release's
   `SHA256SUMS`.
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

## Update Swan Song

Do not update while a game is running, and do not use a development ZIP as an
update for a verified release.

1. Power off the Pocket and back up the complete SD card. At minimum, preserve
   `/Saves/wonderswan/RegionallyFamous.SwanSong/`,
   `/Settings/RegionallyFamous.SwanSong/`, and
   `/Presets/RegionallyFamous.SwanSong/`.
2. Read the new release notes for save, settings, firmware, or migration
   changes.
3. Download the new verified ZIP from the official Releases page and verify it
   against the published `SHA256SUMS` file. For an independent build-origin
   check, also download `signed-quartus-provenance.tar` and
   `release-manifest.json`, extract the former, and verify both candidate audits
   with GitHub CLI using the full source commit from the manifest:

   ```sh
   mkdir -p /tmp/swan-song-signed
   tar -xf signed-quartus-provenance.tar -C /tmp/swan-song-signed
   FINAL_COMMIT="FULL_40_HEX_COMMIT_FROM_RELEASE_MANIFEST"

   gh attestation verify \
     /tmp/swan-song-signed/signed-builds/a/quartus-audit-candidate.json \
     --repo RegionallyFamous/swan-song \
     --signer-workflow github.com/RegionallyFamous/swan-song/.github/workflows/quartus-fit.yml \
     --source-digest "$FINAL_COMMIT" \
     --source-ref refs/heads/main \
     --bundle /tmp/swan-song-signed/signed-builds/a/quartus-audit-candidate.attestation.json

   gh attestation verify \
     /tmp/swan-song-signed/signed-builds/b/quartus-audit-candidate.json \
     --repo RegionallyFamous/swan-song \
     --signer-workflow github.com/RegionallyFamous/swan-song/.github/workflows/quartus-fit.yml \
     --source-digest "$FINAL_COMMIT" \
     --source-ref refs/heads/main \
     --bundle /tmp/swan-song-signed/signed-builds/b/quartus-audit-candidate.attestation.json
   ```

   These commands use GitHub's current online Sigstore trust material. They
   prove two distinct signed workflow executions, not two physical hosts, and
   do not replace the package checksum or Pocket/Dock hardware evidence.
4. Merge the ZIP's `Assets`, `Cores`, and `Platforms` folders into the matching
   folders on the SD card. Keep unrelated cores and personal files.
5. Start one familiar game and confirm that its save and controls behave as
   expected before continuing normal play.

Swan Song updates must not delete games, BIOS files, or the core-specific
`Saves`, `Settings`, and `Presets` folders. If a release note calls for a data
migration, use only the documented preview-first helper for that release.

## Roll back to an earlier release

The safest rollback is to restore the complete SD-card backup made immediately
before the update. That restores the core and its data as one known set.

Replacing only `/Cores/RegionallyFamous.SwanSong` with an older verified core
may be useful for diagnosis, but it is not a data rollback: a newer release may
have already changed saves or settings. Never copy a Pocket Memories blob
between releases or between Swan Song and `agg23.WonderSwan`. If the release
notes do not explicitly authorize an in-place downgrade, restore the full
backup instead.

## Uninstall Swan Song

1. Power off the Pocket and back up the SD card.
2. Remove only `/Cores/RegionallyFamous.SwanSong`.
3. Keep `/Assets/wonderswan/common/` if another WonderSwan core uses your games
   or BIOS files.
4. Keep `/Platforms/wonderswan.json` and `/Platforms/_images/wonderswan.bin` if
   another installed core uses the WonderSwan platform.
5. Keep the Swan Song folders below `/Saves`, `/Settings`, and `/Presets` if
   you may reinstall. Delete those core-specific folders only when you are
   certain their saves and configuration are no longer wanted.

Uninstalling Swan Song does not require removing `agg23.WonderSwan`, and
removing that older core does not require removing Swan Song.

## Mac staging and development packages

The repository includes a read-only-first Mac staging workflow. Its development
mode remains tied to the exact checkout and cannot make an unverified build
safe for ordinary use. Its separate release mode requires trusted published
identity and refuses the current unauthorized policy. See the [Pocket SD staging
guide](https://github.com/RegionallyFamous/swan-song/blob/main/POCKET_SD_STAGING.md)
and [Build and
Test](https://github.com/RegionallyFamous/swan-song/wiki/Build-and-Test) only if
you are helping test the project.
