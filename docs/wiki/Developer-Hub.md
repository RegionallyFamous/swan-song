# Developer Hub

Swan Song is a simulation-first WonderSwan core for the Analogue Pocket. This
wiki summarizes the developer path; the repository Markdown, source, tests,
and machine-readable policies remain the exact reviewable evidence.

> No verified release exists. A green simulation run is necessary, but it is
> not a substitute for an accepted Quartus fit, timing closure, package audit,
> or the physical Pocket and Dock matrix.

## Start here

- [Build and Test](https://github.com/RegionallyFamous/swansong-core/wiki/Build-and-Test)
- [Architecture](https://github.com/RegionallyFamous/swansong-core/wiki/Architecture)
- [Roadmap and current evidence](https://github.com/RegionallyFamous/swansong-core/blob/main/PHASE_STATUS.md)
- [First-class Pocket compliance matrix](https://github.com/RegionallyFamous/swansong-core/blob/main/POCKET_FIRST_CLASS.md)
- [Upstream provenance](https://github.com/RegionallyFamous/swansong-core/blob/main/UPSTREAMS.md)

## Engineering boundaries

The codebase separates three concerns:

1. **Console logic** implements the WonderSwan machine and remains comparable
   with the pinned MiSTer source.
2. **Pocket integration** owns APF commands, data slots, settings, controls,
   video delivery, audio transport, saves, packaging, and hardware pins.
3. **Evidence tooling** builds open/generated fixtures, runs translated-RTL
   simulation, checks metadata and release policy, and records what still
   requires vendor tools or hardware.

Changes should keep those boundaries visible. A Pocket workaround should not
silently redefine shared console behavior, and a simulator result should not
be relabeled as physical proof.

The detailed merge boundary is documented in [MiSTer/Pocket
porting](https://github.com/RegionallyFamous/swansong-core/blob/main/PORTING.md).

## Technical map

| Area | Primary documentation |
| --- | --- |
| Module, clock, memory, and video map | [ARCHITECTURE.md](https://github.com/RegionallyFamous/swansong-core/blob/main/ARCHITECTURE.md) |
| APF lifecycle and data slots | [BUILDING.md](https://github.com/RegionallyFamous/swansong-core/blob/main/BUILDING.md) |
| Launcher, Recent, and Library boundary | [POCKET_LAUNCHER_LIBRARY.md](https://github.com/RegionallyFamous/swansong-core/blob/main/POCKET_LAUNCHER_LIBRARY.md) |
| Core icon and Swan Wake platform art | [CORE_ICON.md](https://github.com/RegionallyFamous/swansong-core/blob/main/CORE_ICON.md), [PLATFORM_ART.md](https://github.com/RegionallyFamous/swansong-core/blob/main/PLATFORM_ART.md) |
| Controls and Dock | [FIRST_CLASS_INPUT_DOCK.md](https://github.com/RegionallyFamous/swansong-core/blob/main/FIRST_CLASS_INPUT_DOCK.md) |
| Frame delivery and orientation | [FRAME_DELIVERY.md](https://github.com/RegionallyFamous/swansong-core/blob/main/FRAME_DELIVERY.md), [VERTICAL_PLAY.md](https://github.com/RegionallyFamous/swansong-core/blob/main/VERTICAL_PLAY.md), [ORIENTATION_TRANSITION.md](https://github.com/RegionallyFamous/swansong-core/blob/main/ORIENTATION_TRANSITION.md) |
| Color and temporal response | [SCREEN_AUTHENTICITY.md](https://github.com/RegionallyFamous/swansong-core/blob/main/SCREEN_AUTHENTICITY.md) |
| Memories/save-state work | [SAVESTATE_FORMAT.md](https://github.com/RegionallyFamous/swansong-core/blob/main/SAVESTATE_FORMAT.md), [SAVESTATE_V2_FORMAT.md](https://github.com/RegionallyFamous/swansong-core/blob/main/SAVESTATE_V2_FORMAT.md), [MEMORIES_STAGING.md](https://github.com/RegionallyFamous/swansong-core/blob/main/MEMORIES_STAGING.md) |
| Homebrew and WonderWitch | [HOMEBREW_WONDERWITCH.md](https://github.com/RegionallyFamous/swansong-core/blob/main/HOMEBREW_WONDERWITCH.md) |
| Physical QA | [HARDWARE_QA_PROTOCOL.md](https://github.com/RegionallyFamous/swansong-core/blob/main/HARDWARE_QA_PROTOCOL.md), [KNOWN_TITLE_COMPATIBILITY.md](https://github.com/RegionallyFamous/swansong-core/blob/main/KNOWN_TITLE_COMPATIBILITY.md) |

## Contribution principles

- Preserve original authorship and pinned provenance.
- Prefer open, generated, or personally authored fixtures.
- Never add commercial ROMs, BIOS files, saves, or private captures.
- Make malformed inputs fail closed.
- Bind claims to executable tests or explicitly name the missing hardware gate.
- Keep deterministic build inputs separate from host clocks and randomness.
- Upstream shared console fixes after the evidence is strong enough to review.

The inherited tree contains a standalone GPL v2 license text, a GPL
v2-or-later program notice, GPL v3-or-later and MIT file notices, and
vendor-specific notices. The standalone GPL v2 text does not by itself license
unheaded files. Release licensing is still under review; consult
[`UPSTREAMS.md`](https://github.com/RegionallyFamous/swansong-core/blob/main/UPSTREAMS.md)
and preserve every file-level notice before redistributing anything.
