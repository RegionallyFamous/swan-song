# Swan Song

**A WonderSwan and WonderSwan Color experience for Analogue Pocket, by
[Regionally Famous](https://github.com/RegionallyFamous).**

Swan Song is an independent openFPGA core being built to make the WonderSwan
feel at home on Analogue Pocket. The goal is simple: respect what made Bandai's
handheld unusual, then give players the reliable saves, thoughtful controls,
clear display choices, and easy setup they expect from a first-class Pocket
experience.

> **Swan Song is still in development. There is not yet a verified public
> release.** The project has extensive automated testing, but the current build
> still needs final licensing review and repeatable testing on real Pocket and
> Dock hardware. The historical protected-main `f0345ee4` FPGA candidate and
> an independent rebuild match byte-for-byte, but newer source changes require
> a fresh full regression, Quartus build, and independent reproduction. None of
> that substitutes for physical product testing or distribution authorization.
> Please do not treat a development build as a finished release.

## Why Swan Song exists

The WonderSwan's identity lives in details that go beyond simply starting a
game. It has two hardware generations, games made for both horizontal and
vertical play, an unusual two-pad control layout, persistent owner information,
and a library full of delightful oddities. Swan Song exists to carry those
details naturally into the Pocket experience.

Swan Song starts from excellent community work. Robert Peip created the
WonderSwan FPGA core that made this project possible, and Adam Gastineau brought
that work to Analogue Pocket. Swan Song is a Pocket-focused continuation of
that foundation. It aims to go further in the areas that matter during everyday
play:

- dependable per-game saves and persistent console settings;
- controls that make sense when a game rotates between horizontal and vertical
  play;
- useful display, color, motion, and fast-forward choices without burying the
  player in jargon;
- careful handling of original WonderSwan and WonderSwan Color games;
- broad, repeatable testing with open test software and private, legally owned
  game collections; and
- compatibility notes that distinguish simulated, physically verified, and
  not-yet-tested behavior.

Swan Song is meant to complement and continue the community's existing work,
not diminish it. That work is the reason this project can exist at all, and
Swan Song intends to contribute generally useful console fixes upstream
whenever they can be shared cleanly.

## What players can expect

The current development work is focused on:

- WonderSwan and WonderSwan Color games in `.ws` and `.wsc` format;
- automatic game-oriented controls for horizontal and vertical play, with
  persistent Horizontal and Vertical overrides;
- fast forward, including an option to keep audio playing;
- persistent per-game saves and separate console settings for the original and
  Color systems;
- presentation options for orientation, motion delivery, LCD response, and
  color;
- a CPU Turbo option for games that benefit from extra headroom;
- friendly handling of missing or invalid files instead of unexplained hangs;
- side-by-side installation with the earlier `agg23.WonderSwan` core, with
  Swan Song's cartridge saves kept in its own core-specific namespace (back up
  first and use the ROM-aware helper for older shared saves); and
- a reproducible core package with a documented origin and test history.

### Controls, rotation, and returning to Swan Song

**Control Layout** can follow each game's horizontal or vertical orientation
automatically, or stay in the layout you choose. It changes the buttons, not
the picture; **Display Orientation** controls the screen presentation. The
[Controls and Settings guide](https://github.com/RegionallyFamous/swan-song/wiki/Controls-and-Settings)
explains the choices.

An optional **Complete Frames 60.9Hz** motion mode reduces modeled frame skips
while keeping tear-free complete frames in steady state. After switching from
direct to buffered output, the live/direct picture remains visible for one
producer-frame priming interval; the complete-frame guarantee begins with the
first completed buffered frame. Standard 59.985 Hz output remains the default
because the optional rate sits close to openFPGA's approximate 61 Hz ceiling
and still needs physical Pocket and Dock acceptance.

Swan Song launches through **openFPGA**, not Pocket's first-party Library.
**Startup Action > openFPGA** shortens the route back, and Pocket firmware 2.6.0
adds a host-owned **Recent** activity category. Its exact Swan Song entry and
relaunch behavior still need physical Pocket validation. See [Compatibility and
Current Limits](https://github.com/RegionallyFamous/swan-song/wiki/Compatibility-and-Current-Limits)
for the current Pocket integration boundaries.

### Known limits

- Physical cartridges are not used; games load from the Pocket SD card.
- Memories and Sleep + Wake are disabled until save states can be proven safe.
- WonderWitch `.fx` programs are not ordinary cartridge images and are not yet
  supported.
- PocketChallenge v2, link-cable play, and multiplayer controllers are not
  currently supported.
- Pocket and Dock behavior still needs hardware-QA testing on physical
  hardware.

## Installing Swan Song

There is nothing for most players to install yet. When the first verified
release is ready, it will appear on this repository's
[Releases page](https://github.com/RegionallyFamous/swan-song/releases) with a
version number, installation notes, and checksums. If Swan Song is later listed
by a trusted Pocket updater, the release notes will say so explicitly.

The expected setup will be:

1. Update the Analogue Pocket to a supported firmware version.
2. Install the Swan Song release package on the Pocket SD card.
3. Add your own legally obtained WonderSwan and WonderSwan Color BIOS files.
4. Add your own `.ws` and `.wsc` game images.
5. Open **openFPGA**, choose the **WonderSwan** platform, then select **Swan
   Song** and a game.

The BIOS files will be named `bw.rom` and `color.rom`; BIOS and game files will
live in `/Assets/wonderswan/common/`. A normal player will **not** need Quartus,
Docker, a virtual machine, or a cloud server. Those are development tools, not
installation requirements.

The `framework.version_required` value in `core.json` makes Analogue OS 2.3 the
minimum firmware that may load Swan Song. That loader minimum is not yet a
promise that every 2.3-era host behavior is supported: launch qualification
targets and recommends Analogue OS 2.6.0, and the verified release notes will
state the final evidence-backed support floor.

On macOS, take care when copying the release folders: Finder can replace a
same-named folder instead of merging it. The release guide will include a safe
Mac installation path. Swan Song's read-only-first staging tool already has an
explicit release-verification mode, but the checked-in release policy currently
blocks installation because distribution and licensing are not authorized yet.

## Bring your own games and BIOS

Swan Song does not include, download, or provide links to commercial games,
Bandai BIOS files, or WonderWitch firmware. Use dumps you are legally entitled
to use in your country. Please do not upload ROMs or BIOS files to GitHub, an
issue report, or a public testing service.

## Help and documentation

Use the live player guides for:

- [installing Swan Song](https://github.com/RegionallyFamous/swan-song/wiki/Install-Swan-Song)
- [updating, rolling back, uninstalling, and keeping another WonderSwan core](https://github.com/RegionallyFamous/swan-song/wiki/Install-Swan-Song#update-swan-song)
- [starting and playing games](https://github.com/RegionallyFamous/swan-song/wiki/Playing-Games)
- [controls and settings](https://github.com/RegionallyFamous/swan-song/wiki/Controls-and-Settings)
- [saves and migration](https://github.com/RegionallyFamous/swan-song/wiki/Saves-and-Migration)
- [compatibility and current limits](https://github.com/RegionallyFamous/swan-song/wiki/Compatibility-and-Current-Limits)
- [troubleshooting and bug reports](https://github.com/RegionallyFamous/swan-song/wiki/Troubleshooting-and-Bug-Reports)

Technical contributors can start at the [Developer
Hub](https://github.com/RegionallyFamous/swan-song/wiki/Developer-Hub).
Release owners and reviewers should use the checked-in
[release decision record](RELEASE_DECISIONS.md).

### Something not working?

With the Pocket SD card mounted, open Terminal in a downloaded Swan Song source
folder and run:

```bash
python3 scripts/swan_song_doctor.py --sd-root "/Volumes/POCKET"
```

Replace `/Volumes/POCKET` with the card's actual path. By default Swan Song
Doctor performs no content or namespace writes (filesystem reads may update
access times). It checks the complete player-visible installation, BIOS
filenames and sizes, valid whole-bank game sizes and per-game settings
locations, older WonderSwan data, and unsafe SD-card paths. It never uploads
ROMs, BIOS files, or saves. BIOS identification is available only when you
explicitly add `--identify-bios`; game contents are never read. See the
player-friendly [troubleshooting guide](https://github.com/RegionallyFamous/swan-song/wiki/Troubleshooting-and-Bug-Reports)
or the [complete Doctor reference](SWAN_SONG_DOCTOR.md) for help reading the
result and for carefully previewing optional repairs.

Found a problem? Open an
[issue](https://github.com/RegionallyFamous/swan-song/issues) and include the
game title and region, Pocket firmware, Swan Song version or commit, selected
system type, and whether you were playing on Pocket or Dock. If practical, say
whether the same behavior appears in the earlier Pocket or MiSTer core. Never
attach copyrighted game or BIOS data.

## Credits

Swan Song is maintained by **Regionally Famous** under the independent core ID
`RegionallyFamous.SwanSong`.

- WonderSwan FPGA core: [Robert Peip](https://github.com/RobertPeip)
  ([Patreon](https://www.patreon.com/FPGAzumSpass))
- Original Analogue Pocket port: [Adam Gastineau](https://github.com/agg23)
- Swan Song icon and **Swan Wake** platform artwork: **Regionally Famous**
  ([art provenance](PLATFORM_ART.md))

Many emulator, homebrew, documentation, and hardware-research projects also
make this work possible. Detailed provenance and pinned upstream revisions are
maintained in the project documentation and will remain part of the technical
wiki. That record preserves spiritualized1997's credit for the predecessor's
historical platform image even though Swan Song no longer distributes it.
