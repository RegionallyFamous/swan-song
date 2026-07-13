# Pocket launcher and Library boundary

Last researched: **2026-07-13**, against Pocket firmware **2.6.0**.

## Result

Swan Song can be a polished, first-class **openFPGA** core, but the public
Analogue Platform Framework (APF) does not provide a supported way to add a
third-party core or an SD-card ROM to Pocket's top-level **Library**. The
shortest supported path is:

1. Set Pocket's **Startup Action** to **openFPGA**.
2. Launch Swan Song once so Pocket 2.6.0 can place the activity in openFPGA's
   host-owned **Recent** category.
3. Let Swan Song's persistent cartridge data slot reuse the last selected
   `.ws` or `.wsc` file when the core is opened again.

That is the supported launcher target. It still needs final Pocket hardware
validation; it is not the same thing as a dedicated WonderSwan tile in the
top-level OS Library.

## What each Pocket surface actually does

| Surface | Public behavior | What Swan Song can control |
| --- | --- | --- |
| openFPGA platform entry | APF reads the installed core definitions, platform metadata, and platform image. | The core name, platform grouping/details, `/Platforms/_images/wonderswan.bin`, About text, asset browser, and runtime UI. |
| Startup Action > openFPGA | Boots to openFPGA. Analogue added this OS setting in firmware 1.1 beta. | Nothing beyond being a valid installed core; there is no documented per-core or per-title startup field. |
| openFPGA Recent | Firmware 2.6.0 records recent openFPGA usage activity. | No documented API can pre-seed, pin, rename, or promise the contents of Recent. The host owns it. |
| Remembered title | APF data-slot parameter bit 9 persists a browsed filename. | Swan Song sets that bit for slot 0, so a normal core relaunch is expected to reuse the last title. This acts only after the host opens the core. |
| Analogue Library | Analogue documents Library as a cartridge collection database: playing a recognized cartridge adds its entry, date, and play time. | There is no Library-registration field in the public core, data, platform, or instance definitions. |
| Memories and screenshots | The host keeps Memories per openFPGA core and automatically captures openFPGA screenshots. | Swan Song supplies truthful video and, once implemented and certified, save-state data. These features do not create Library entries. |

Primary references: [firmware 1.1 beta](https://www.analogue.co/support/pocket/firmware/1.1-beta),
[firmware 2.6.0](https://www.analogue.co/support/pocket/firmware/2.6.0),
[openFPGA 1.1 beta 7 changelog](https://www.analogue.co/developer/docs/changelog/1-1-beta-7),
and [`core.json`](https://www.analogue.co/developer/docs/core-definition-files/core-json).

## Platform art is not Library art

The two similarly named image systems have different consumers:

- `/Platforms/_images/wonderswan.bin` is named from the openFPGA platform
  shortname. Analogue documents it as the graphic for a user-supplied
  openFPGA platform. Swan Song already ships the correctly placed platform
  image and metadata.
- `/System/Library/Images/<platform>/<crc32>.bin` is Library artwork. Analogue
  documents the lowercase CRC32 of one asset, or of the deterministic
  concatenation of multiple assets, as the filename. The image decorates an
  entry that Pocket already knows; the file is not an executable, manifest,
  database record, or launcher shortcut.

Consequently, copying a WonderSwan image pack into `System/Library/Images`
would not register a WonderSwan platform or make `.ws`/`.wsc` assets
launchable from Library. It would be an unconsumed artwork guess, so Swan Song
does not install one. See Analogue's [Platform Metadata](https://www.analogue.co/developer/docs/platform-metadata)
and [Library image](https://www.analogue.co/developer/docs/library)
specifications.

This distinction is also visible in mature updater behavior. At pupdate commit
[`07452a1`](https://github.com/mattpannella/pupdate/tree/07452a17af897d7c6d041fcc4dcad5100df67e48),
platform image packs are installed under `Platforms/_images`, while separate
Library image packs are copied under `System/Library/Images` for cartridge
platforms. Neither operation adds a new PocketOS launch surface. The public
openFPGA inventory is likewise an updater catalogue, despite the word
“Library” in its project name; it is not Pocket's on-device Library database.

A package inspection reached the same result. The latest public
[Spiritualized GBC 1.3.0 release](https://github.com/spiritualized1997/openFPGA-GB-GBC/releases/tag/v1.3.0)
contains `Assets`, `Cores`, and `Platforms` plus a core icon, but no Library or
launcher manifest. The current upstream
[openfpga-wonderswan package](https://github.com/agg23/openfpga-wonderswan/tree/073213a2e5992cff23b174d17763cb6354ee862b)
uses the same APF package boundary. Audits of
[pupdate](https://github.com/mattpannella/pupdate/tree/07452a17af897d7c6d041fcc4dcad5100df67e48)
and [Pocket Updater](https://github.com/RetroDriven/Pocket_Updater/tree/06adff2f9509b399c60f89ed8d7d4a60db1a2022)
found core installation, platform-art setup, and related maintenance features,
not a supported PocketOS launcher-registration mechanism.

## Physical cartridges and adapters

APF 1.2 lets a core request cartridge power, check an Analogue adapter ID, and
offer **Play Cartridge** in its asset browser. That is an openFPGA boot option,
not Library registration. It also requires real compatible electrical hardware
and cartridge-bus logic.

Analogue's current adapter set covers TurboGrafx-16/PC Engine/SuperGrafx, Neo
Geo Pocket Color, and Atari Lynx, with Game Gear sold separately. It does not
include WonderSwan. Swan Song therefore correctly leaves cartridge power off
(`cartridge_adapter: -1`) and does not advertise cartridge support. A future
WonderSwan adapter would be a separate hardware and FPGA project and, without
new PocketOS support from Analogue, would still start under openFPGA. See the
[APF 1.2 cartridge-adapter contract](https://www.analogue.co/developer/docs/changelog/1-2)
and [Analogue Pocket Adapter Set](https://store.analogue.co/products/analogue-pocket-adapter-pack).

## Unsupported routes we will not disguise as integration

Analogue states that Pocket's smaller System FPGA is used exclusively for
Analogue OS, while third-party cores run in the Primary Core FPGA through APF.
The documented SD layout exposes core, asset, save, setting, preset, and
Memories locations, but no third-party PocketOS application or Library-record
manifest. The official package format is therefore the `Assets`, `Cores`, and
`Platforms` tree Swan Song already uses.

As of this audit, no public supported PocketOS plug-in, per-core home-screen
shortcut, or custom-firmware extension point is documented. Patching firmware,
injecting guessed Library database records, impersonating a first-party core,
or modifying the System FPGA would be a different reverse-engineering project,
not an openFPGA feature. It would be fragile across firmware updates and outside
the supported SDK. Analogue's EULA also restricts modifying, reverse
engineering, bypassing, or distributing derivative portions of its software,
subject to applicable law. Swan Song will not ship such a patch.

GB Studio's `/GB Studio` path is also not a general launcher API. It accepts
`.pocket` Game Boy Studio files and cannot wrap a WonderSwan bitstream or ROM.

References: [openFPGA overview](https://www.analogue.co/developer/docs/overview),
[SD folder structure](https://www.analogue.co/developer/docs/directories-and-sd-folder-structure),
and the [Analogue EULA](https://assets.analogue.co/pdf/43478bf701eb4905172acbecc3babae9/Analogue%2BEULA%2BAugust%2B14%2B2022.pdf).

## First-class plan within the supported boundary

The most useful work is to make the supported path feel immediate and reliable:

- retain framework/PocketOS 2.3 as the technical minimum and recommend
  PocketOS 2.6.0 for its Recent and quit-to-openFPGA experience;
- validate Startup Action, Recent, last-title relaunch, clean title switching,
  and save flushes on real Pocket hardware;
- keep the WonderSwan platform art, metadata, About text, controls, display
  modes, presets, and Dock experience polished;
- never claim top-level Library, physical-cartridge, or first-party launcher
  integration unless Analogue publishes a real API and the implementation is
  verified against it.

If Analogue later documents a third-party Library or home-screen registration
contract, that new host API is the correct place to add true top-level
integration. No current APF metadata should be invented in anticipation of it.
