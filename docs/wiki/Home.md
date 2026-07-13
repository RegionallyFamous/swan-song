# Swan Song

Swan Song is a WonderSwan and WonderSwan Color core being built especially for
the Analogue Pocket by **Regionally Famous**.

> **Development status:** Swan Song does not have a verified public release
> yet. The current code has extensive automated test coverage, but its FPGA
> build, timing, and complete Pocket and Dock experience still need final
> hardware verification. The [Releases
> page](https://github.com/RegionallyFamous/swan-song/releases) is the only
> place that will identify an installable public release.

## Why Swan Song exists

The existing WonderSwan FPGA work is the reason this project is possible.
[Robert Peip](https://github.com/RobertPeip) created the system core, and
[Adam Gastineau](https://github.com/agg23) brought it to the Analogue Pocket.
Swan Song continues that work with a deliberately Pocket-focused goal: make
WonderSwan games feel at home on the Pocket, while making every important
claim reviewable and testable.

The project is designed to improve the Pocket experience through:

- careful horizontal and vertical controls on both Pocket and Dock;
- safer, exact-size cartridge saves and persistent console owner data;
- support for conventional and compact `.ws` and `.wsc` images up to the
  core's implemented 16 MiB limit;
- a convenient action for entering the original BIOS owner setup;
- display choices that distinguish neutral output from optional emulator-based
  color and persistence effects;
- reproducible builds, broad automated regression tests, and explicit release
  gates instead of unsupported compatibility promises; and
- honest boundaries around Pocket Library, physical cartridges, Memories,
  WonderWitch, and features the public openFPGA interface cannot provide.

This is a continuation, not a dismissal of the upstream cores. Shared
console-logic improvements should flow upstream after they are verified.

## Player guide

- [Install Swan Song](https://github.com/RegionallyFamous/swan-song/wiki/Install-Swan-Song)
- [Playing Games](https://github.com/RegionallyFamous/swan-song/wiki/Playing-Games)
- [Controls and Settings](https://github.com/RegionallyFamous/swan-song/wiki/Controls-and-Settings)
- [Saves and Migration](https://github.com/RegionallyFamous/swan-song/wiki/Saves-and-Migration)
- [Compatibility and Current Limits](https://github.com/RegionallyFamous/swan-song/wiki/Compatibility-and-Current-Limits)
- [Troubleshooting and Bug Reports](https://github.com/RegionallyFamous/swan-song/wiki/Troubleshooting-and-Bug-Reports)

Developers can start at the [Developer
Hub](https://github.com/RegionallyFamous/swan-song/wiki/Developer-Hub).

## What Swan Song does not include

Swan Song does not include or download commercial games, WonderSwan BIOS
files, WonderWitch firmware, or private test captures. You must provide your
own legally obtained game and BIOS images. Never upload those files to an
issue, this repository, a test server, or a public cloud service.

The independent Pocket core identity is `RegionallyFamous.SwanSong`. The
project preserves its complete [upstream provenance and
credits](https://github.com/RegionallyFamous/swan-song/blob/main/UPSTREAMS.md).
