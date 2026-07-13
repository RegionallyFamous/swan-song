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
> still needs final licensing review, a verified FPGA build, and repeatable
> testing on real Pocket and Dock hardware. Please do not treat a development
> build as a finished release.

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
- automatic game-oriented controls for horizontal and vertical play;
- fast forward, including an option to keep audio playing;
- persistent per-game saves and separate console settings for the original and
  Color systems;
- presentation options for orientation, smoother motion, LCD response, and
  color;
- a CPU Turbo option for games that benefit from extra headroom;
- friendly handling of missing or invalid files instead of unexplained hangs;
- side-by-side installation with the earlier `agg23.WonderSwan` core (back up
  saves before alternating between cores, because both may use the same
  per-game save file); and
- a reproducible core package with a documented origin and test history.

Swan Song will use **openFPGA**. Analogue does not currently document a
supported way for third-party cores or their games to appear in Pocket's
first-party Library. Setting **Startup Action > openFPGA** and using Pocket's
openFPGA **Recent** list should make return visits quick, but Swan Song will not
claim first-party Library integration that Pocket does not provide.

### Known limits

- Physical cartridges are not used; games load from the Pocket SD card.
- Memories and Sleep + Wake are disabled until save states can be proven safe.
- WonderWitch `.fx` programs are not ordinary cartridge images and are not yet
  supported.
- PocketChallenge v2, link-cable play, and multiplayer controllers are not
  currently supported.
- Pocket and Dock behavior still needs release-candidate testing on physical
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

On macOS, take care when copying the release folders: Finder can replace a
same-named folder instead of merging it. The release guide will include a safe
Mac installation path.

## Bring your own games and BIOS

Swan Song does not include, download, or provide links to commercial games,
Bandai BIOS files, or WonderWitch firmware. Use dumps you are legally entitled
to use in your country. Please do not upload ROMs or BIOS files to GitHub, an
issue report, or a public testing service.

Private collection testing is designed so the game files remain on hardware
you control; public reports can use anonymous results without exposing game
names, paths, or file hashes.

## Help and documentation

Player guides and deeper technical material are moving to the
[Swan Song wiki](https://github.com/RegionallyFamous/swan-song/wiki) so this
front page can stay focused on playing the games. Planned sections include:

- installation and first launch;
- controls, rotation, saves, and display options;
- compatibility and known limitations;
- Pocket and Dock testing;
- building and release verification; and
- architecture and contributor documentation.

The wiki is now open and will be expanded before the first verified release.
Until each guide moves there, the documents in this repository describe the
development work in progress.

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
- Platform artwork: [spiritualized1997](https://github.com/spiritualized1997)

Many emulator, homebrew, documentation, and hardware-research projects also
make this work possible. Detailed provenance and pinned upstream revisions are
maintained in the project documentation and will remain part of the technical
wiki.
