# Physical Pocket and Dock QA protocol

This is the reproducible hardware acceptance-record protocol for Swan Song. It
does not contain a hardware result and does not enable a release. The generator
creates only `pending` cases and a false attestation. The verifier establishes
schema completeness, identity/hash integrity, and the presence of a human
attestation. It cannot mechanically prove that the tester used the stated
hardware, performed the procedure, interpreted a capture correctly, or told
the truth. Physical acceptance remains a human review decision.

Swan Song is maintained by Regionally Famous and the inventory must identify
the installed core as `RegionallyFamous.SwanSong`. Robert Peip's WonderSwan
system core and Adam Gastineau's Pocket port remain credited in `README.md`;
historical platform-art provenance remains in `UPSTREAMS.md`. Regionally
Famous authored the current Swan Song core icon and **Swan Wake** platform art.
The independent APF ID and new artwork are not claims to inherited core work.

The protocol was rechecked on 2026-07-15 against Pocket firmware 2.6.0. The
official release publishes version, date, and MD5 and adds openFPGA Recent:
[firmware 2.6.0](https://www.analogue.co/support/pocket/firmware/2.6.0).
That release also adds **Auto Dim** and **Auto Off** under **Settings → PocketOS
→ Power Saving**, with defaults of five minutes and two hours respectively.
Analogue's current
[`data.json`](https://www.analogue.co/developer/docs/core-definition-files/data-json)
contract says a nonvolatile slot is unloaded on core exit and its data flush
occurs on root-menu Quit, Pocket power-off, or sleep. The official
[core boot process](https://www.analogue.co/developer/docs/core-boot-process)
orders shutdown as Reset Enter, persistent-register capture, nonvolatile-slot
readout, then FPGA wipe. Analogue separately warns that the five-second
[forced-power-off procedure](https://www.analogue.co/developer/docs/debugging-aids)
can lose in-progress saves. The dedicated `auto_off_dirty_save_flush` case
therefore observes firmware 2.6.0's configured idle Auto Off without a power
button, menu, input, or USB SD intervention; it is not satisfied
by normal Quit, manual power-off, or forced power-off.
Analogue documents automatic native-resolution PNG screenshots for openFPGA
cores ([1.1 beta 7](https://www.analogue.co/developer/docs/changelog/1-1-beta-7)),
RTC-at-start and keyboard/mouse Dock slots
([1.1 beta 6](https://www.analogue.co/developer/docs/changelog/1-1-beta-6)),
the normalized four-slot PAD bus
([Bus Communication](https://www.analogue.co/developer/docs/bus-communication)),
and display modes plus Dock-specific aspect support
([2.0](https://www.analogue.co/developer/docs/changelog/2-0)).
Firmware 1.1 beta 5 also added a
[Chip32 cycle limit during crash](https://www.analogue.co/developer/docs/changelog/1-1-beta-5),
but Analogue does not publish that limit or the VM instruction rate. The ROM
validation loop's 1,048,576-poll bound is therefore an instruction guard, not
a wall-clock guarantee. The `invalid_rom_negative` case therefore includes a
target-firmware calibration: temporarily replace only the reviewed package's
Chip32 loader with a source-reviewed diagnostic variant that runs the same
bounded poll loop while forcing the PMP status to remain pending. Record the
diagnostic binary hash and complete source delta, prove Swan Song's visible
timeout appears before Pocket's firmware cycle limit, then reinstall and
rehash every payload from the inventory-bound reviewed package. The ordinary
invalid-footer path cannot substitute for that calibration, and the diagnostic
loader is never a release payload.

The current [`input.json`](https://www.analogue.co/developer/docs/core-definition-files/input-json)
page calls Controls read-only and the core-definition overview says remapping
is coming soon, while the official [firmware 2.4](https://www.analogue.co/support/pocket/firmware/2.4)
notes say beta remapping applies to all four Dock controllers. Because those
official statements conflict, this protocol records actual firmware 2.6.0
Pocket and Dock behavior instead of requiring either outcome.

The same current `input.json` page also documents that a slot-0-derived file
under `/Presets/AuthorName.CoreName/Input/` overrides the packaged controls
definition. The official
[`interact.json`](https://www.analogue.co/developer/docs/core-definition-files/interact-json)
page documents the parallel `/Presets/AuthorName.CoreName/Interact/` override,
the default persistent-value path under `/Settings/AuthorName.CoreName/Interact/`,
and mirrored per-asset settings paths. The official
[SD directory reference](https://www.analogue.co/developer/docs/directories-and-sd-folder-structure)
likewise defines Presets as per-asset definitions and Settings as persistent
core/per-asset values. Consequently, hashing the 13 installed package payloads
does not by itself prove which controls/menu values APF presented at runtime.
The prelaunch namespace baseline and physical menu captures below close that
gap for this run.

## Safety and privacy boundary

- Keep the inventory, firmware update, BIOSes, ROMs, device-ID source files,
  and evidence bundle private. Do not add them to Git.
- Use only personally dumped or openly licensed ROMs. This repository neither
  supplies nor validates ownership of test assets.
- Put a stable device identifier in each private device-ID file. The generated
  manifest retains only its SHA-256, not the identifier.
- Record observations only from the named physical Pocket/Dock run. Simulation,
  source inspection, and another RBF cannot satisfy a physical case.
- A failed test remains `fail`; an incomplete test remains `pending`. There is
  no skip state because every catalogue entry is an acceptance requirement.
- Preserve original evidence. Editing a capture, log, save, or manifest after
  hashing makes verification fail.

## 1. Assemble the private inventory

### Fast macOS workspace scaffold

The read-only-first scaffold creates the private directory layout, stamps the
run/operator identity into the reviewed inventory template, and generates the
open 896 KiB compact-ROM probe plus mono/Color SRAM persistence probes for
footer save types `03`, `04`, and `05` in one command. It does not search for or copy
firmware, BIOS, commercial ROM, save, device-ID, or capture bytes. The target
must be outside this repository and must not already exist.

Preview the exact plan, then add `--apply` after reviewing it:

```sh
python3 scripts/prepare_hardware_qa_workspace.py \
  --output "$HOME/Swan Song Hardware QA" \
  --run-id swan-song-final-01 \
  --operator-name "Regionally Famous" \
  --operator-organization "Regionally Famous"

python3 scripts/prepare_hardware_qa_workspace.py \
  --output "$HOME/Swan Song Hardware QA" \
  --run-id swan-song-final-01 \
  --operator-name "Regionally Famous" \
  --operator-organization "Regionally Famous" \
  --apply
```

The resulting `NEXT_STEPS.md` contains absolute commands for that workspace.
Its `inventory.json` intentionally retains placeholders for observed hardware,
controllers, and the operator-selected private inputs; the strict generator
will reject it until those are replaced.

The generated type-`03`/`04`/`05` ROMs contain only repository-authored 80186
code, metadata, provenance text, and padding. They initialize every declared
64 KiB SRAM bank, then require the prior generation to survive relaunch before
alternating patterns. Status `11` means initialized, `22`/`21` mean persisted
and toggled, and `ee` means corrupt or aliased. Their manifest and checksum
file bind the exact generator and every output; no commercial ROM bytes are
used.

Copy [`hardware-qa-inventory.example.json`](hardware-qa-inventory.example.json)
outside the repository and replace every placeholder. Paths may be absolute or
relative to the inventory file. The inventory binds:

- the installed Pocket firmware update by the official MD5 plus computed
  SHA-256;
- Pocket and Dock model/revision plus privacy-preserving device-ID hashes;
- the `installed_dist_path` tree's exact 13-file Pocket-facing payload
  catalogue: all
  seven core JSON files, core icon/info, platform definition/art, installed
  `.rev` bitstream, and installed Chip32 image, plus the raw Quartus RBF;
- exact mono and color BIOS bytes;
- every test ROM's SHA-256, model, native orientation, footer-derived exact
  save type/capacity, declared save-media class, and RTC flag;
- built-in, wired Dock, wireless Dock, keyboard, and mouse identities and modes.

Generation rejects a `.rev` that is not the exact same-size bit-reversal of the
raw RBF. Both files must be at least 64 KiB. A current official openFPGA
template RBF inspected for this protocol is 787,952 bytes; the smaller 64 KiB
floor is only a conservative truncation/tiny-fixture detector, not proof of a
valid Cyclone V bitstream or a replacement for Quartus build evidence.
The public installed-payload manifest contains exactly the canonical allowlist;
symlinks, missing members, or a `core_json_path`, `interact_json_path`,
or `installed_bitstream_path` that points outside that tree fail. Legal text,
private ROM/BIOS/save bytes, raw RBF, QA artifacts, and package provenance are
not in this public catalogue, avoiding private-data disclosure and circular
evidence. The installed `interact.json` identity is included in the public
environment, and generation rejects any persistent-variable list other than
the reviewed nine-setting catalogue. This binds the worksheet to the packaged
default menu instead of relying only on the RBF. It does not claim APF loaded
that default: the fresh-SD Presets/Settings audit and menu observations below
establish that separate physical fact.
It also requires both `.ws` and `.wsc`, horizontal and vertical coverage, RTC
plus non-RTC titles, and at least one ROM for every supported footer save type:
`00`, `01`, `02`, `03`, `04`, `05`, `10`, `20`, and `50`. The verifier reads
the footer from the hashed ROM instead of trusting the inventory's coarse
`save_media` label. It binds types `01`/`02` to 32 KiB SRAM, `03` to 128 KiB
SRAM, `04` to 256 KiB SRAM, `05` to 512 KiB SRAM, and `10`/`20`/`50` to
128-byte/2-KiB/1-KiB EEPROM. Type `00` must declare no save. Every inventory ROM
must have a valid reset/header footer, supported metadata, and additive
checksum and must meet the implemented 64 KiB through 16 MiB whole-64-KiB-bank
boundary. Conventional power-of-two images retain the legacy mapping path;
compact images are right-aligned into the next-power-of-two mapper aperture.
The fixed inventory includes the original generated 896 KiB compact
probe so the lower `0xff` prefix, reset vector, footer, and `0x0fffff` mask can
be checked without third-party ROM content. The compact case accepts only that
deterministic repository-generator identity, SHA-256
`b4a2c985906ac04c6622080bb1f1f3ac4b3895784c5594f4ba97cd45e6935979`,
not an arbitrary valid 896 KiB image. BIOS filenames and sizes must be exactly
`bw.rom`/4096 and `color.rom`/8192.

Install FFmpeg on the operator Mac before recording evidence (`brew install
ffmpeg` if it is absent). The verifier decodes at least one real frame or audio
duration from every screenshot, photo, video, and audio artifact. A renamed,
header-only, truncated, zero-frame, or undecodable file cannot satisfy a case.

From the repository root, generate the fixed probe at the example inventory
path before generating the manifest:

```sh
python3 sim/verilator/generate_non_power_two_probe.py \
  /private/swan-song-qa/private/compact-896k.wsc
```

Use the firmware file actually installed for the run. V1 is deliberately pinned
to firmware 2.6.0 and its official MD5
`d5be2c99e436081266810594117db496`. A later firmware requires a reviewed code
and protocol update that pins its official identity, followed by the full
catalogue; an inventory author cannot self-declare a different accepted hash.

Materialize the reviewed QA-only stuck-pending Chip32 diagnostic into a new
private directory before beginning the negative-input case:

```sh
python3 scripts/build_chip32_pending_diagnostic.py \
  --output /private/swan-song-qa/chip32-pending-diagnostic \
  --apply
```

Without `--apply`, the command is a read-only plan. It accepts only the pinned
release assembly and encoded image, replaces the single `pmpr r1,r2` status
read with the official Chip32 encoding for `xor r2,r2`, preserves
the `0x00100000` timeout and image size, and writes owner-only source, binary,
README, and JSON provenance files. The manifest binds the complete source
delta, exact two changed byte offsets, and release/diagnostic SHA-256 values.
Create a throwaway copy of the signed candidate's installed payload tree for
the calibration and place `chip32-pending.bin` there as `chip32.bin`; never
alter the signed candidate or use this diagnostic in a release package. After
the observation, reinstall the signed candidate and rehash every installed
payload before running any other acceptance case.

## 2. Generate the pending manifest

Create an empty evidence directory, then run:

```sh
python3 scripts/pocket_hardware_qa.py generate \
  --inventory /private/swan-song-qa/inventory.json \
  --output /private/swan-song-qa/evidence/manifest.json
```

The command hashes the inventory files and writes the complete 33-case
catalogue. It refuses to overwrite an existing manifest. Every generated case
has `status: "pending"`, false checks, no attachments, and no timestamps. The
physical attestation is also false. This output is intentionally not accepted.

Run the verifier immediately to confirm the fail-closed state:

```sh
python3 scripts/pocket_hardware_qa.py verify \
  --inventory /private/swan-song-qa/inventory.json \
  --manifest /private/swan-song-qa/evidence/manifest.json
```

Expected result: exit status 2 and an error naming the first pending case.

Generate the local operator worksheet beside the manifest:

```sh
python3 scripts/pocket_hardware_qa.py worksheet \
  --inventory /private/swan-song-qa/inventory.json \
  --manifest /private/swan-song-qa/evidence/manifest.json \
  --output /private/swan-song-qa/evidence/operator-worksheet.md
```

This command first runs the same inventory, environment, schema, and artifact
validation as the verifier, while allowing the generated pending cases. It
then writes a human-readable status page with all 33 cases, every physical
check, one strict-valid ROM/controller selection from the bound inventory, and
a deterministic minimum artifact plan beneath `evidence/files/<case-id>/`.
The plan supplies exact suggested artifact IDs, filenames, extensions, and
paths; it also marks the APF-audit and save-snapshot labels that the verifier
requires verbatim. Re-run the command after each fully recorded pass or fail to
refresh progress. Omit `--output` to preview the Markdown on standard output.

The worksheet is deliberately read-only: it creates no evidence files, does
not edit the manifest, does not set checks or statuses, and does not complete
the final human attestation. Checking boxes in the Markdown has no effect.
Captured bytes, UTC times, sizes, hashes, observations, and review decisions
must still be entered from the physical run. The worksheet itself is an
operator aid, not a QA artifact, and must not be registered in `artifacts`.

### Safer one-case recorder

Instead of editing a large manifest while a case is in progress, use the
session recorder. Every command is a dry run until `--apply` is added. It locks
the private evidence workspace, keeps the authoritative case pending, copies
each capture from the workspace's owner-only `private/` directory with an
exact hash, and publishes a completed case only after the separate human result
JSON passes the full verifier.

```sh
python3 scripts/pocket_hardware_qa_session.py start-case \
  --inventory /private/swan-song-qa/inventory.json \
  --manifest /private/swan-song-qa/evidence/manifest.json \
  --case pocket_horizontal_input \
  --started-at 2026-07-15T12:00:00Z \
  --rom-id horizontal-sram \
  --controller-id pocket-built-in \
  --apply

python3 scripts/pocket_hardware_qa_session.py ingest-artifact \
  --inventory /private/swan-song-qa/inventory.json \
  --manifest /private/swan-song-qa/evidence/manifest.json \
  --source /private/swan-song-qa/private/pocket-horizontal.mov \
  --kind video \
  --label "physical controls capture" \
  --captured-at 2026-07-15T12:02:00Z \
  --apply

python3 scripts/pocket_hardware_qa_session.py finish-case \
  --inventory /private/swan-song-qa/inventory.json \
  --manifest /private/swan-song-qa/evidence/manifest.json \
  --result /private/swan-song-qa/private/pocket-horizontal-result.json \
  --apply
```

The result JSON must explicitly name the case, `pass` or `fail`, completion
time, every exact check boolean, and human notes under the documented
`SWAN_SONG_HARDWARE_QA_CASE_RESULT_V1` envelope. The recorder never completes
the final physical-hardware attestation; independent review remains required.

`finish-case` prepares the exact successor hash in the private sidecar before
atomically publishing the manifest. If power loss or another interruption
occurs after publication but before sidecar cleanup, do not delete the sidecar
by hand. Preview, then apply, the exact recovery proof:

```sh
python3 scripts/pocket_hardware_qa_session.py recover-session \
  --inventory /private/swan-song-qa/inventory.json \
  --manifest /private/swan-song-qa/evidence/manifest.json

python3 scripts/pocket_hardware_qa_session.py recover-session \
  --inventory /private/swan-song-qa/inventory.json \
  --manifest /private/swan-song-qa/evidence/manifest.json \
  --apply
```

Recovery never writes a case or artifact. It removes only a prepared sidecar
whose final manifest hash, case selection, exact artifact records, and full
authoritative verification already match the published successor. An active,
unpublished, invalid, or diverged session remains untouched so the original
`finish-case` can be retried or the discrepancy investigated.

## 3. Execute and record each case

Use the generated check names as the worksheet. For a completed case:

1. Set `status` to `pass` only if every named check was physically observed.
2. Record UTC `started_at` and `completed_at` as `YYYY-MM-DDTHH:MM:SSZ`.
3. List only the exact inventory `rom_ids` and `controller_ids` used. Selection
   is case-specific: single-title cases require exactly one matching title;
   orientation/save-pair cases require exactly the two relevant titles; Pocket,
   wired, wireless, mixed, and negative-device cases require only their exact
   controller classes. Listing the whole inventory for every case is rejected.
4. Set every check to `true` and write a specific observation in `notes`.
   For `controls_behavior_recorded`, state whether Controls was read-only or
   editable on Pocket and Dock. If editing was offered, record application,
   Reset to Defaults, relaunch persistence, and per-asset scope; the boolean
   means the behavior was captured, not that remapping succeeded.
5. Add the required captures under the manifest directory and register each in
   the top-level `artifacts` array. Reference their IDs from the case.
6. If any check fails, use `status: "fail"`, retain the evidence, fix the core
   in a different build, and start a new run ID and manifest.

For `fresh_sd_startup`, first complete the distribution lifecycle without
launching Swan Song while `agg23.WonderSwan` is installed. Record a UTF-8 log
labeled exactly `side-by-side update uninstall audit`. It must hash the
predecessor core tree and saves, install a prior Swan Song development package
beside it, show both distinct core entries, update Swan Song to the exact
inventory-bound package, and prove that only Swan Song's installed payloads
changed while its mutable Saves/Settings/Presets namespaces were preserved.
Then remove only `Cores/RegionallyFamous.SwanSong`, retain the shared
`wonderswan` platform definition/art while the predecessor still needs it, and
prove the predecessor core and saves remain operational. Reinstall the
inventory-bound Swan Song package and rehash all 13 installed payloads.

After that reinstall, establish the APF override baseline before Pocket
launches the exact reviewed package. The two Swan Song Presets and Settings
namespaces must still be absent; if the distribution exercise created either
one, fail the case and begin a new clean run rather than normalizing the card
after the fact. The SD may contain unrelated cores, but both complete Swan Song
namespaces must be absent:

- `/Presets/RegionallyFamous.SwanSong` — this proves there is no mirrored
  `/Presets/RegionallyFamous.SwanSong/Input/<path_to_slot0_asset>.json` or
  `/Presets/RegionallyFamous.SwanSong/Interact/<path_to_slot0_asset>.json`
  capable of overriding either packaged definition for any inventory ROM;
- `/Settings/RegionallyFamous.SwanSong` — this proves neither the default
  `/Interact/interact_persist.json` nor a mirrored per-asset settings file can
  preload stale values on the first launch.

Capture a UTF-8 log labeled exactly `fresh-sd APF namespace baseline`. It must
record the run ID, UTC inspection time, mounted SD identity, explicit absent
result for both paths, recursive `/Presets` and `/Settings` listings (or their
absence), and SHA-256 values for the installed `input.json` and `interact.json`
that match `environment.core.installed_payloads`. After this capture, do not
add anything below the Swan Song Presets namespace. If the SD is mounted again
to mutate a negative-test file, repeat the namespace absence check in the same
log before resuming.

On the first launch, create a photo or video labeled exactly
`fresh-sd bound input menu` showing these packaged mappings: A = Horz A/Vert
X3, B = Horz B/Vert X4, X = Horz Y3/Vert X2, Y = Horz Y4/Vert X1, L = Horz
Y1/Vert A, R = Horz Y2/Vert B, Start = Start, and Select = Fast Forward. Create
a second photo or video labeled exactly `fresh-sd bound interact defaults`
showing Reset core and Console Setup as actions plus all nine initial values:
System Type Auto, CPU Turbo Off, Triple Buffer On, Motion / LCD Response Off,
Display Orientation Auto, Landscape 180° Off, Color Profile Raw RGB444, Control Layout
Auto, and Audio in Fast Forward On. The case requires seven visual artifacts in
total so these two APF-menu records do not displace the launcher art/icon
evidence. A mismatch means a Preset, Settings value, or wrong package affected
the run; mark the case failed rather than normalizing the menu by hand.

For `console_eeprom_lifecycle`, begin with both fixed files absent at
`/Saves/wonderswan/RegionallyFamous.SwanSong/mono.eeprom` and
`color.eeprom`. Use one `.ws` and one `.wsc` title plus the operator's original
4 KiB/8 KiB BIOS dumps.
Make a visible setup edit through each original BIOS, then capture both exact
files after factory creation, setup edit, quit/relaunch, model switch, title
switch, ordinary reset, and full Pocket power cycle. The 14 `save` artifact
labels are exactly `console-eeprom {mono|color} {stage}`, where stage is
`factory-created`, `setup-edited`, `quit-relaunch`, `model-switch`,
`title-switch`, `ordinary-reset`, or `power-cycle`. The verifier requires every
mono snapshot to be 128 bytes, every Color snapshot to be 2,048 bytes, each
setup hash to differ from its factory hash, and every later hash to match the
edited image. For each model, enter the flow through **Core Settings > Console
Setup**; confirm that the original BIOS owner screen appears as though Start
were held at power-on, and that the action does not change Display Orientation
or the native control matrix. To exercise the **menu focus** hold, deliberately
remain in the PocketOS menu for at
least two seconds after selecting the action, then exit and prove the armed
gesture still reaches the owner screen; this distinguishes menu-focus hold from
the shorter reset/Start counters. Capture at least two visual records showing the
original BIOS flows and a UTF-8 log that records absent-file checks, both shutdown/flush
boundaries, exact SD paths, device/model/title transitions, and hashes.

For `all_save_types_lifecycle`, select exactly one ROM for each of the nine
supported footer types. Type `00` must create no cartridge save. For every
nonzero type, capture three `save` artifacts with exact labels
`cartridge-save type-{01|02|03|04|05|10|20|50} {stage}`, where stage is
`initialized`, `quit-relaunch`, or `power-cycle`. Each artifact must be exactly
the footer-derived payload capacity plus 12 bytes only when that inventory ROM
has RTC. The initialized hash must differ from the written quit/relaunch hash,
and the power-cycle hash must reproduce the quit/relaunch hash. The verifier
rejects missing types, duplicate substitutions, wrong sizes, extra save
snapshots, unchanged writes, and power-cycle mismatches.

For `auto_off_dirty_save_flush`, use the generated mono type-`03` persistence
probe whose ROM SHA-256 is
`1c04f468ac445616e9613b08dd874aadc83bc214f9b192f777e845019b4c4ccb`.
Run on an undocked Pocket with the probe's slot-0-derived save absent. Launch,
wait for the probe to complete, and use normal root-menu **Quit** to create the
baseline. Before the second launch, disable **Auto Dim**, configure **Auto Off**
to the exact interval recorded in the audit log, and start one uninterrupted
video. Relaunch the same probe, then provide no input and do not enter a menu,
press the power button, Dock the Pocket, or attach/detach USB SD.
The video must cover the entire idle interval through the automatic off state.
Only after Pocket has automatically turned off may the operator inspect the SD
with a card reader and capture the flushed save. Reinstall the SD, power Pocket
on, relaunch the same probe, wait, use normal Quit, and capture the third save;
that final launch proves the automatically flushed generation was loaded before
the probe toggled it again.

The case has these exact checks:

- `auto_off_enabled_and_interval_recorded`;
- `auto_dim_disabled_and_recorded`;
- `pocket_undocked`;
- `baseline_created_by_normal_quit`;
- `no_input_menu_or_power_button_during_idle`;
- `automatic_off_observed_after_configured_interval`;
- `automatic_off_flushed_exact_generation_2`;
- `relaunch_loaded_generation_2`; and
- `exact_path_sizes_hashes_and_timeline_recorded`.

Register exactly three 131,072-byte `save` artifacts with these labels and
SHA-256 values:

| Exact label | Required SHA-256 |
|---|---|
| `auto-off type-03 generation-1 status-11 baseline` | `6e28073ba6d548e82170923a7c42e505d566358111cfd42e4848cc3fc1b7e9c4` |
| `auto-off type-03 generation-2 status-22 flushed` | `c8b0ef643dbcb0ab8acfa642aa0d203f778bf6a73e3dadd8cc47ecf01e7a9a6b` |
| `auto-off type-03 generation-1 status-21 relaunch` | `0f216531d087d0f491ca9460552e55ec2eebb8eb5d78f92676e0902422cbfe9a` |

Also register one uninterrupted `video` labeled exactly
`PocketOS 2.6 Auto Off uninterrupted dirty-save shutdown` and one UTF-8 `log`
labeled exactly `PocketOS 2.6 Auto Off dirty-save audit`. The log must record
the firmware and Pocket identities, undocked state, Auto Dim and Auto Off values, exact
slot-0-derived save path, ROM hash, UTC launch/automatic-off/SD-inspection/
relaunch/Quit timeline, all file sizes and hashes, and an explicit statement
that no disallowed intervention occurred. Removing the SD, using USB SD,
pressing power, entering a menu, or otherwise inspecting the save before Auto
Off completes invalidates the case rather than demonstrating a shutdown flush.

For `settings_options_and_persistence`, exercise Auto, forced WonderSwan, and
forced WonderSwan Color across both models and prove that a runtime System Type
change remains inert until reset. Record a baseline and an observed rate change
for CPU Turbo without audio/video instability. Change all nine persistent user
settings—System Type, CPU Turbo, Triple Buffer, Motion / LCD Response, Display
Orientation, Landscape 180°, Color Profile, Control Layout, and Audio in Fast
Forward—and prove their UI and runtime effects survive ordinary reset,
quit/relaunch, title switch, Dock transition, and full power cycle. Then run
**Reset all to defaults** and prove every setting returns to its declared
default. Reset core and Console Setup are actions and must remain momentary.

Use the fresh-SD baseline—not a copied settings file—as the origin of that
persistence test. After the first clean launch/quit, confirm that APF created
the documented global file
`/Settings/RegionallyFamous.SwanSong/Interact/interact_persist.json` during
this run. For each selected slot-0 asset, also derive the official mirrored
per-asset path below `/Settings/RegionallyFamous.SwanSong/Interact/` and prove
that it was not used; those paths apply only when a matching per-asset
`interact.json` was loaded, which this release baseline forbids. Attach a UTF-8
log labeled exactly `settings APF persistence path audit` containing complete
namespace trees, file sizes, mtimes, and SHA-256 values after clean/default
creation, after changing all nine values, after quit/relaunch and title switch,
after power cycle, and after Reset all to defaults. APF may create other
per-core bookkeeping during the run, so the acceptance fact is provenance from
the recorded empty baseline plus explained transitions—not an unsupported
claim that the whole Settings root remains empty.

For `video_buffer_modes`, set Motion / LCD Response to Off before evaluating
direct mode:
Triple Buffer Off must use the live/direct path, while Triple Buffer On must
present only completed frames. Exercise both orientations on Pocket and Dock,
transition in both directions, and look for mixed ownership, stale rotation,
tearing in buffered mode, or resync. Then prove either temporal response mode
forces the buffered path and that returning Motion / LCD Response to Off
restores the selected direct path. Finally select **Complete Frames 60.9Hz**,
prove it also forces complete-frame buffering, and record Pocket and Dock
Statistics rather than inferring the delivered rate from source. Exercise
0/270/180-degree presentation and generic display modes `0x20/0x30/0x40` on
both outputs, and transition standard -> 60.9 Hz -> standard. On each
direct-to-buffered change, record the one producer-frame priming interval in
which the live/direct picture can remain visible. Beginning with the first
completed buffered frame, reject tearing, mixed frames, stale rotation,
HDMI/Pocket resync, or a partial-line cadence change.

For `invalid_rom_negative`, attach a UTF-8 log labeled exactly
`Chip32 stuck-pending poll-guard calibration`. Besides the ordinary malformed
input results, record the inventory-bound release loader and diagnostic loader
SHA-256 values, the complete diagnostic source delta, unchanged raw RBF hash,
Pocket firmware identity, start/visible-error times, and whether the host cycle
limit appeared. The diagnostic package must force the PMP validation status to
stay pending without shortening the release poll bound. Restore the exact
inventory-bound package, verify all installed-payload hashes, and boot a valid
ROM before passing the case.

For `long_run_stability`, disable Pocket **Auto Dim** and **Auto Off** before
the run and record both UI values in the case log; an unattended dim, sleep, or
power-off is not a core stability result. Keep **Complete Frames 60.9Hz** active
for the full minimum 120 minutes, include physically observed Pocket and Dock
segments, and record Statistics before and after the soak. The existing video,
audio, save, input, crash, resync, and drift checks remain mandatory.

For `wrong_size_bios_negative`, try exact one-byte boundary mutations on both
required files: 4,095 and 4,097-byte `bw.rom`, and 8,191 and 8,193-byte
`color.rom`. Each must be rejected before game execution; restoring exact
4,096/8,192-byte files must recover without reinstalling the core.

For `unused_hardware_interfaces`, use a documented non-invasive measurement
method and record the instrument/setup in the log. Across boot, gameplay, and
shutdown, confirm the framework `cartridge_adapter: -1` power policy; Bank
3/2/1 inputs remain high impedance; Bank 0's nibble is the implemented high
output; pins 30/31 remain under host control/input as declared; the unadvertised
link SO/SI/SCK/SD lines are not driven; IR transmit remains off; and IR receive
disable remains asserted. A source tie-off or simulation is not physical
evidence. If a line cannot be observed safely on the named hardware, leave the
case pending rather than inferring it.

The fixed catalogue covers:

| Area | Required cases |
|---|---|
| Startup and launcher | `agg23.WonderSwan` side-by-side install, Swan Song update/uninstall/reinstall isolation, predecessor save/tree preservation, Fresh SD, prelaunch Swan Song Presets/Settings namespaces absent, packaged Input and Interact/default menus physically observed, no Presets introduced during the run, Swan Wake platform art/About legibility, centering, contrast, and clipping, core icon legibility and centering in positive/negative Core List and Core Boot Screen contexts, Startup Action to openFPGA, Recent creation/relaunch, last-title reuse, Reset all to defaults |
| Compact ROM | Generated 896 KiB probe, `0xff` lower-prefix behavior, right-aligned reset vector/footer, 1 MiB aperture and `0x0fffff` mask, power-of-two regression |
| Negative boot | Missing mono/color BIOS; 4,095/4,097-byte mono and 8,191/8,193-byte Color BIOS rejection; too-small/misaligned/oversized ROM; invalid compact footer/checksum with visible **ROM footer/checksum rejected** error; target-firmware stuck-pending fault injection with diagnostic Chip32/source-delta identity, visible timeout before the host cycle limit, exact release-package restoration, and recovery with corrected inputs |
| Disabled features | Memories and quick-load actions unavailable or rejected without game-state mutation |
| Pocket input | Complete horizontal and vertical matrices, simultaneous directions, Start, held and latched Fast Forward, observed Controls behavior without assuming editability or persistence; repeated menu pause/resume during visible action, Fast Forward cleared, resume independent of neutral PAD rearm, no held-chord leak or duplicate memory/DMA action |
| Presentation | Auto/forced horizontal/vertical, 180-degree landscape, no input remap, transition-frame integrity |
| Display/screenshots | Raw and ares color, all LCD-response modes, generic display modes `0x20/0x30/0x40`, native 224x144 Pocket PNG, grayscale recovery |
| Buffering | Explicit direct and triple-buffer paths, clean bidirectional transitions, both orientations on Pocket and Dock, temporal-response forced buffering, return to direct mode, Complete Frames 60.9Hz forced buffering, Pocket/Dock Statistics, 0/270/180-degree rotations, all three generic display modes, recorded direct-to-buffered priming intervals, standard/60.9 transitions, and no tearing or resync after the first completed buffered frame |
| User settings | Auto/forced System Type reset semantics, CPU Turbo off/on rate and stability, persistence of all nine settings across reset/relaunch/title/Dock/power transitions, current-run global `interact_persist.json` creation, no mirrored per-asset settings used, namespace transition hashes, actions remaining momentary, Reset all to defaults |
| Dock input | Wired and wireless matrices, recorded Controls/D-pad/analog behavior, hot-unplug while held, reconnect, dedicated menu and Select+Down fallback; repeated pause/resume before neutral rearm with no stuck input or held-chord leak |
| Dock video | HDMI 0/270/180-degree presentation, aspect/crop, display modes, first portrait frame, no resync |
| Negative devices | P2 gamepad, P3 keyboard, P4 mouse, disconnect, then P1 recovery |
| Save data | Every footer type `00/01/02/03/04/05/10/20/50` and exact 0/32/32/128/256/512-KiB or 128/2,048/1,024-byte capacity, conditional 12-byte RTC trailer, cartridge SRAM/EEPROM plus fixed mono/Color console EEPROM absent/create/quit/relaunch/model-switch/title-switch/ordinary-reset/power-cycle/flush lifecycles, exact before/after hashes, and a dedicated undocked PocketOS 2.6 Auto Off dirty-write flush/reload proof |
| RTC | Epoch initialization, minute/day crossings, quit/relaunch, power cycle, title isolation, trailer hashes, and wall-clock advancement across a sustained PocketOS menu pause |
| Negative saves | Short, oversized, malformed RTC, wrong type, supported type-`0x01` canonical 32 KiB behavior, documented legacy EEPROM case, recovery |
| Audio | Pocket and Dock 48 kHz captures, stereo identity, silence, extrema, pops/drift, Fast Forward sound modes, menu pause/resume transitions with continuous I2S presentation and no audible discontinuity |
| Whole-device lifecycle | Dock/undock without reset or corruption; a dedicated undocked Auto Off shutdown with Auto Dim disabled, no intervention, and an exact dirty-save flush; and a minimum 120-minute Complete Frames 60.9Hz Pocket/Dock stability run with Auto Dim/Auto Off disabled and recorded plus pre/post Statistics |
| Physical interfaces | Cartridge power and translator directions, unadvertised link-port high impedance, IR transmitter off/receiver disabled, no unexpected boot/play/shutdown activity, recorded electrical measurement method |

The verifier also enforces the appropriate ROM and controller class for each
case. Listing an unrelated horizontal ROM for vertical input, a Pocket control
for the wired-Dock case, or a non-RTC ROM for RTC lifecycle is rejected.

## 4. Evidence schema

The manifest envelope is `hardware_qa` with magic
`SWAN_SONG_HARDWARE_QA_EVIDENCE_V2`. Unknown or missing members fail. Its
top-level members are:

- `run_id`, `created_at`, and `operator`, copied exactly from the private
  inventory;
- `environment`, regenerated and compared byte-for-data from all inventory
  inputs on every verification;
- `artifacts`, the hashed evidence registry;
- `cases`, exactly one of every current catalogue case with no additions or
  omissions;
- `attestation`, the final physical-observation and review declaration.

Each artifact has exactly `id`, `kind`, `path`, `label`, `captured_at`, `size`,
and lowercase `sha256`. Paths are POSIX-relative to the manifest directory;
absolute paths, `..`, missing files, empty files, symlinks, hard links, repeated
paths, and hash mismatches fail. Allowed evidence kinds are:

- `pocket_screenshot`: a PNG whose IHDR is exactly the core's native 224x144;
- `photo`: a PNG or JPEG hardware/HDMI photograph;
- `video`: MP4, MOV, MKV, or WebM capture;
- `audio`: WAV or FLAC capture;
- `save`: an exact SD-card save snapshot;
- `log`: a nonempty UTF-8 Pocket or tester log.

Each completed case must reference enough evidence of the required kinds, and
every capture timestamp must fall inside that case's interval. Save/RTC cases
require multiple save snapshots plus logs; screenshot, audio, HDMI, and input
cases require their corresponding media. Unreferenced artifacts fail final
verification. One artifact ID may belong to only one case: cross-case reuse is
rejected so each observation has an independent evidence record.

The APF override baseline is also fail-closed on exact artifact labels. The
fresh-SD case needs logs named `fresh-sd APF namespace baseline` and
`side-by-side update uninstall audit`, one photo/video named `fresh-sd bound
input menu`, and one photo/video named `fresh-sd bound interact defaults`. The
invalid-ROM case needs one log named `Chip32 stuck-pending poll-guard
calibration`; the settings case needs one log named `settings APF persistence
path audit`. Generic, relabeled, screenshot-only claims are rejected. The
verifier establishes the files' identity and timing, while the reviewer remains
responsible for confirming that the logs and visible menus support the checks.

The console-EEPROM case adds content relationships to those generic checks:
its 14 exact-size, exact-label snapshots must prove that the original-BIOS edit
changed each factory image and that quit/relaunch, model/title switching,
ordinary reset, and power cycle reproduced the edited SHA-256 without cross-bank
replacement. The attested log and visual evidence remain necessary because a
hash alone cannot prove how a state transition was performed.

The all-save-types case similarly binds its selected ROMs' footer-derived
capacities to 24 exact-label snapshots. For each nonzero type the initialized
image must change after the recorded write, quit/relaunch and power-cycle hashes
must match, and the file must contain exactly the payload plus the conditional
12-byte RTC trailer. A true check without those byte relationships is rejected.

The Auto Off case binds one exact generated ROM, three exact-label 131,072-byte
save snapshots with fixed content hashes, one exact-label uninterrupted video,
and one exact-label audit log. The three snapshots must prove status/generation
`11/1` after normal Quit, `22/2` after unattended Auto Off, and `21/1` after the
next relaunch and normal Quit. The fixed hashes establish the complete expected
save contents, while the human reviewer must confirm that the video and timeline
show the configured idle shutdown and exclude manual power, force-off, menu,
Dock, input, and USB SD intervention.

Media checks are deliberately superficial signature/extension checks. The
tool reads PNG IHDR dimensions for Pocket screenshots and sniffs basic
PNG/JPEG, WAV/FLAC, and MP4/MOV/MKV/WebM signatures; it does not decode media,
run `ffprobe`, establish duration/sample rate/content, recognize a real Pocket,
or judge image/audio quality. A human reviewer must open every artifact and
decide whether it actually supports the named checks.

The final attestation requires all three booleans to be true:
`physical_hardware_observed`, `results_not_inferred_from_simulation`, and
`evidence_reviewed`, plus a reviewer and UTC review time. The tool cannot prove
human honesty, but it prevents a generated template, missing observation, or
unreviewed evidence set from accidentally becoming an accepted result.

## 5. Verify and archive

Run the same strict command after all evidence is recorded:

```sh
python3 scripts/pocket_hardware_qa.py verify \
  --inventory /private/swan-song-qa/inventory.json \
  --manifest /private/swan-song-qa/evidence/manifest.json
```

Success prints `VALID evidence schema, hashes, and human attestation`, the run
ID, 33 required cases, artifact count, and the SHA-256 of the exact manifest
bytes that were parsed. It also prints that this is not mechanical proof.
Archive the private inventory and complete evidence directory together. The
manifest is not independently reproducible without the exact private firmware,
device-ID source files, core artifacts, BIOSes, and ROMs. A successful command
means the evidence record is internally consistent, not that hardware QA has
been independently certified.

## Relationship to release evidence

The stable assembler is the only public release path. It first verifies two
complete Quartus candidate bundles from distinct signed workflow executions for
the exact release commit and epoch, requires different fresh job nonces and
byte-identical RBF/build-ID files, and then constructs Release Evidence V2 for
the lower-level package validator. The signatures distinguish workflow
executions, not physical hosts; they do not replace this hardware protocol.

Release Evidence V2 requires exact filename/size/SHA-256 identities for both
this accepted manifest and its private inventory. Packaging reruns the strict
hardware verifier, requires all 33 cases plus the physical/evidence-review
attestations, and records the run, case, artifact, firmware, and device/core
facts in package provenance. It also binds the normalized signed build pair and
requires the tested raw RBF, version, date, complete nine-setting persistence
catalogue, and every installed payload identity to match the release ZIP.
Staging independently repeats the complete hardware and signed-pair structural
comparison. Public `signed-quartus-provenance.tar` retains the two candidate
audits and GitHub attestation bundles for independent online
`gh attestation verify`; it contains none of this protocol's private inventory,
firmware, device identity, ROMs, or captures. A bare
`pocket_hardware` or `dock_hardware` boolean therefore cannot authorize a
release. Presets and Settings are deliberately not added to that immutable
13-file package catalogue: Presets are prohibited mutable test state, while
Settings are runtime output. Their prelaunch absence, current-run provenance,
and menu effects are instead bound through the accepted hashed QA artifacts.

The separate `RegionallyFamous.SwanSong` namespace may coexist with
`agg23.WonderSwan`. Swan Song cartridge saves are core-specific below
`/Saves/wonderswan/RegionallyFamous.SwanSong/...`. If testing migrated a legacy
shared save, preserve the source, record the ROM-aware conversion plan and
before/after hashes, and test quit/relaunch; never perform an unvalidated manual
namespace copy. If testing copied fixed EEPROM/settings/presets, preserve the
historical source tree and do it in a separate non-release migration run. A
release-acceptance run must begin with the two Swan Song APF namespaces absent;
copied Settings or Presets invalidate its baseline. Never transplant
`/Memories/Beta/agg23.WonderSwan`; Memories are disabled and no cross-ID format
migration exists.

A release reviewer may accept the final hardware gates only after this verifier
succeeds for the exact core/RBF under review and the private evidence has been
inspected. Preserve the complete private evidence directory with the bound
inventory even though only its identities and public-safe verification summary
enter package provenance. Publication also remains blocked until the separate
licensing authorization and accepted final-commit Quartus fit/TimeQuest
evidence are complete.
