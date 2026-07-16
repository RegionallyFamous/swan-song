# Swan Song

Swan Song is a WonderSwan and WonderSwan Color core being built especially for
the Analogue Pocket by **Regionally Famous**.

> **Development status:** Swan Song does not have a verified public release
> yet. Historical protected-main candidate `f0345ee4` and an independent
> rebuild match byte-for-byte and pass the strict four-corner timing audit;
> newer source changes still require a fresh regression and FPGA build. The
> complete Pocket and Dock experience and distribution clearance also need
> final verification. The [Releases
> page](https://github.com/RegionallyFamous/swansong-core/releases) is the only
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
- a built-in open IPL with no external BIOS-file requirement;
- display choices that distinguish neutral output from optional emulator-based
  color and persistence effects;
- reproducible builds, broad automated regression tests, and explicit release
  gates instead of unsupported compatibility promises; and
- honest boundaries around Pocket Library, physical cartridges, Memories,
  WonderWitch, and features the public openFPGA interface cannot provide.

This is a continuation, not a dismissal of the upstream cores. Shared
console-logic improvements should flow upstream after they are verified.

## Player guide

- [Install Swan Song](https://github.com/RegionallyFamous/swansong-core/wiki/Install-Swan-Song)
- [Playing Games](https://github.com/RegionallyFamous/swansong-core/wiki/Playing-Games)
- [Controls and Settings](https://github.com/RegionallyFamous/swansong-core/wiki/Controls-and-Settings)
- [Saves and Migration](https://github.com/RegionallyFamous/swansong-core/wiki/Saves-and-Migration)
- [Compatibility and Current Limits](https://github.com/RegionallyFamous/swansong-core/wiki/Compatibility-and-Current-Limits)
- [Troubleshooting and Bug Reports](https://github.com/RegionallyFamous/swansong-core/wiki/Troubleshooting-and-Bug-Reports)

Developers can start at the [Developer
Hub](https://github.com/RegionallyFamous/swansong-core/wiki/Developer-Hub).

## What Swan Song does not include

Swan Song does not include or download commercial games, WonderWitch firmware,
or private test captures. You must provide your own legally obtained game
images. Never upload those files to an issue, this repository, a test server,
or a public cloud service.

The independent Pocket core identity is `RegionallyFamous.SwanSong`. The
project preserves [documented provenance and known
credits](https://github.com/RegionallyFamous/swansong-core/blob/main/UPSTREAMS.md);
final distribution clearance remains pending.
