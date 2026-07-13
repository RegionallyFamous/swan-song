# Per-game Pocket presets

Swan Song can use Analogue Platform Framework (APF) per-asset overrides to give
each WonderSwan ROM its own video, performance, audio, and Controls settings.
The repository includes a deterministic generator:

```sh
python3 scripts/pocket_per_game_preset.py \
  --sd-root /Volumes/POCKET \
  --asset "Vertical/Example.wsc" \
  --orientation vertical \
  --color-profile ares \
  --triple-buffer on \
  --lcd-response persistence \
  --cpu-turbo off \
  --fast-forward-audio on
```

The asset may instead be written as the full Pocket-style path
`/Assets/wonderswan/common/Vertical/Example.wsc`. It does not have to exist on
the computer running the tool. The generator never opens, hashes, copies, or
catalogues a ROM.

## What APF officially supports

These are documented APF behaviors, not inferred conventions:

- A per-asset Interact definition is loaded from
  `/Presets/AuthorName.CoreName/Interact/<path_to_slot0_asset>.json` and
  completely overrides the core's default `interact.json`.
- Its persistent values are stored separately at
  `/Settings/AuthorName.CoreName/Interact/<path_to_slot0_asset>.json` and
  matched by the Interact element IDs.
- A per-asset Controls definition is loaded from
  `/Presets/AuthorName.CoreName/Input/<path_to_slot0_asset>.json` and overrides
  the core's default `input.json`.
- Pocket derives all three paths from data slot 0. The mirrored path includes
  the platform and `common` directories, and replaces the asset's extension
  with `.json`.

The authoritative references are Analogue's
[`interact.json` documentation](https://www.analogue.co/developer/docs/core-definition-files/interact-json),
[`input.json` documentation](https://www.analogue.co/developer/docs/core-definition-files/input-json),
and [SD directory structure](https://www.analogue.co/developer/docs/directories-and-sd-folder-structure).
Analogue OS 1.1 beta 5 added host-managed remapping for cores that provide an
`input.json`; see the official
[1.1 beta 5 changelog](https://www.analogue.co/developer/docs/changelog/1-1-beta-5).

For example, if slot 0 is:

```text
/Assets/wonderswan/common/Vertical/Example.wsc
```

the generator writes:

```text
/Presets/agg23.WonderSwan/Interact/wonderswan/common/Vertical/Example.json
/Presets/agg23.WonderSwan/Input/wonderswan/common/Vertical/Example.json
```

The Interact output is a complete copy of Swan Song's menu definition with
only these `defaultval` fields changed:

| Setting | CLI option | Choices |
| --- | --- | --- |
| Display Orientation | `--orientation` | `auto`, `horizontal`, `vertical` |
| Landscape 180 degrees | `--landscape-180` | `off`, `on` |
| Color profile | `--color-profile` | `raw`, `ares` |
| Triple Buffer | `--triple-buffer` | `off`, `on` |
| LCD Response | `--lcd-response` | `off`, `2-frame`, `persistence` |
| CPU Turbo | `--cpu-turbo` | `off`, `on` |
| Audio in Fast Forward | `--fast-forward-audio` | `off`, `on` |

The `persistence` LCD-response choice is a finite three-frame blend; it is not
an unbounded phosphor or pixel-history simulation. The former CLI spelling
`3-frame` remains an explicit compatibility alias and generates byte-identical
JSON. The former option name `--flicker` is also accepted as an alias for
`--lcd-response`. Either non-off LCD-response choice uses completed-frame history even if
Triple Buffer is off. Forced
vertical presentation takes precedence over Landscape 180 degrees, so the tool
rejects that ineffective combination instead of silently accepting it.

## Per-game Controls

By default, the generator also creates the path-mirrored `Input` definition.
This selects a per-asset APF Controls definition/namespace; it does **not**
pre-remap any button. Every newly generated Input file is initially an exact
copy of the core's default eight mappings. Open the running game's **Core
Settings > Controls** menu on Pocket to perform the actual host-managed remap.
The generated definition preserves all eight verified Swan Song mapping IDs,
dual-orientation labels, and APF keycodes so Pocket can associate those
functions with that slot-0 asset.

The public `input.json` schema defines the control mapping surface, but does not
document a JSON format or SD path for the user's saved remap values. Therefore,
the tool does not fabricate or modify host-owned remap state. This is a cautious
inference from the current public documentation: the per-asset Input override
is supported, while the remap store remains an Analogue OS implementation
detail.

Use `--controls inherit` to create no Input override and retain the core-wide
Controls definition. This option does not delete a per-game Input file that is
already on the SD card.

## Persistence and replacement

APF loads persistent Interact values immediately before Reset Exit. Consequently,
an existing per-game file under `/Settings/.../Interact/` can take precedence
over newly generated defaults. Choose **Reset all to defaults** in Core Settings
to apply the new `defaultval` values for that game.

The generator refuses to overwrite either preset by default. Pass `--force` to
replace both after reviewing the command. It also rejects parent traversal,
wrong platform roots, malformed extensions, injected core IDs, and symlinks in
the destination tree. The two outputs are preflighted together so a normal
conflict cannot leave only half a preset pair.

`--core-id` exists for a future authorized core rename. Its value must exactly
match the installed `/Cores/AuthorName.CoreName/` directory or APF will not find
the presets.

## Privacy and release packaging

The JSON contents contain only the core's public APF menu definitions and
chosen defaults. They contain no ROM bytes, title database, CRC, checksum,
publisher metadata, artwork, firmware, or BIOS data. A user-visible ROM name is
present only in the required path mirror on that user's SD card.

Per-game presets should intentionally remain outside the release core archive.
They are user-local state tied to user-local slot-0 paths; bundling them would
create a brittle game-name catalogue and could overwrite personal choices.
Swan Song's strict core-package validator therefore continues to admit only
the core's `Assets`, `Cores`, and `Platforms` roots. The generator and this
documentation are source-repository tools, not files copied into the Pocket
core ZIP.

Instance JSON is not used here. Analogue documents instances as slot-0 assets
that require the Instance JSON parameter bit and a `.json` extension. Swan
Song's slot 0 remains a normal `.ws`/`.wsc` cartridge slot, so changing it to an
instance loader merely to obtain presets would change the launch workflow and
is unnecessary. See Analogue's
[`<instance>.json` documentation](https://www.analogue.co/developer/docs/core-definition-files/instance-json).

## Verification

Run the offline adversarial suite with:

```sh
python3 scripts/pocket_per_game_preset_test.py
```

The suite proves exact path mirroring, all setting values, byte-for-byte
determinism, no ROM reads or embedded ROM metadata, complete Input cloning,
overwrite behavior, all-or-nothing preflight, CLI errors, and traversal/core-ID/
symlink rejection. The following physical acceptance matrix is required before
calling per-game Controls or Dock behavior certified:

| Surface | Required exercise | Pass condition |
| --- | --- | --- |
| Pocket built-in controls | With a fresh per-game Input definition, inspect all eight defaults, remap each function once, relaunch the title, then choose **Reset to Defaults**. | Every dual-orientation label and default key is correct; all eight remaps take effect and survive relaunch; reset restores only the declared defaults. |
| Per-asset isolation | Create definitions for two personally owned ROM paths, assign visibly different remaps, alternate launches, then test a third title using `--controls inherit`. | The two per-asset mappings do not leak into each other; the inherited title retains the core-wide mapping. Treat failure as an Analogue OS behavior gap, because the public docs do not define the saved-remap store. |
| Dock digital controller (`type 2`) | Test a wired digital pad and a second representative wired or wireless pad. Exercise D-pad, all six remappable action/trigger functions, Start, and Fast Forward in both native orientations. | Dock Player 1 produces the same canonical functions and labels as Pocket, with no brand-specific swaps or missing simultaneous inputs. |
| Dock analog-capable controller (`type 3`) | Repeat the digital matrix over both USB and Bluetooth where supported, using the controller's digital D-pad. Move both analog sticks through their full range without pressing the D-pad. | Digital controls match Pocket. Analog motion alone produces no WonderSwan direction because Swan Song intentionally does not synthesize D-pad bits from `cont1_joy`. |
| Native X/Y independence | In horizontal and vertical titles, hold each D-pad direction while pressing every face/trigger action individually and in representative chords. | Directional input and the opposite native X/Y action cluster remain independently visible; no remap aliases one Pocket control onto both native clusters at once. |
| Hot plug and focus | Enter/leave the menu, insert/remove Pocket from Dock, reconnect both tested pads, and repeat while no control is held and while a control is released during the transition. | No stuck direction, action, Start, or Fast Forward state; control resumes on Player 1 without resetting or changing the per-asset mapping. |
| Non-gamepad packets | Connect a Dock keyboard and mouse, then disconnect all controllers. | Keyboard (`type 4`), mouse (`type 5`), disconnected (`type 0`), and reserved packet types cannot become WonderSwan buttons. This is source-simulated, but still needs a physical smoke test. |

The intended per-asset Controls definition must appear in every case. Any
host-managed remap must remain scoped to the intended game before release. The
public APF documentation specifies per-asset Input lookup and host remapping,
but does not publish the remap-store path or formally guarantee its persistence
scope; that portion of the matrix cannot be replaced by an offline test.
