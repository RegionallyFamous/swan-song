# Physical Pocket and Dock QA protocol

This is the reproducible hardware acceptance-record protocol for Swan Song. It
does not contain a hardware result and does not enable a release. The generator
creates only `pending` cases and a false attestation. The verifier establishes
schema completeness, identity/hash integrity, and the presence of a human
attestation. It cannot mechanically prove that the tester used the stated
hardware, performed the procedure, interpreted a capture correctly, or told
the truth. Physical acceptance remains a human review decision.

The protocol was researched on 2026-07-13 against Pocket firmware 2.6.0. The
official release publishes version, date, and MD5 and adds openFPGA Recent:
[firmware 2.6.0](https://www.analogue.co/support/pocket/firmware/2.6.0).
Analogue documents automatic native-resolution PNG screenshots for openFPGA
cores ([1.1 beta 7](https://www.analogue.co/developer/docs/changelog/1-1-beta-7)),
RTC-at-start and keyboard/mouse Dock slots
([1.1 beta 6](https://www.analogue.co/developer/docs/changelog/1-1-beta-6)),
the normalized four-slot PAD bus
([Bus Communication](https://www.analogue.co/developer/docs/bus-communication)),
and display modes plus Dock-specific aspect support
([2.0](https://www.analogue.co/developer/docs/changelog/2-0)).
The current [`input.json`](https://www.analogue.co/developer/docs/core-definition-files/input-json)
page calls Controls read-only and the core-definition overview says remapping
is coming soon, while the official [firmware 2.4](https://www.analogue.co/support/pocket/firmware/2.4)
notes say beta remapping applies to all four Dock controllers. Because those
official statements conflict, this protocol records actual firmware 2.6.0
Pocket and Dock behavior instead of requiring either outcome.

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

Copy [`hardware-qa-inventory.example.json`](hardware-qa-inventory.example.json)
outside the repository and replace every placeholder. Paths may be absolute or
relative to the inventory file. The inventory binds:

- the installed Pocket firmware update by the official MD5 plus computed
  SHA-256;
- Pocket and Dock model/revision plus privacy-preserving device-ID hashes;
- the installed `core.json`, raw Quartus RBF, and installed `.rev` bitstream;
- exact mono and color BIOS bytes;
- every test ROM's SHA-256, model, native orientation, save media, and RTC flag;
- built-in, wired Dock, wireless Dock, keyboard, and mouse identities and modes.

Generation rejects a `.rev` that is not the exact same-size bit-reversal of the
raw RBF. Both files must be at least 64 KiB. A current official openFPGA
template RBF inspected for this protocol is 787,952 bytes; the smaller 64 KiB
floor is only a conservative truncation/tiny-fixture detector, not proof of a
valid Cyclone V bitstream or a replacement for Quartus build evidence.
It also requires both `.ws` and `.wsc`, horizontal and vertical coverage, SRAM
and EEPROM, and RTC plus non-RTC titles. ROMs must meet the core's implemented
64 KiB through 16 MiB power-of-two boundary. BIOS filenames and sizes must be
exactly `bw.rom`/4096 and `color.rom`/8192.

Use the firmware file actually installed for the run. V1 is deliberately pinned
to firmware 2.6.0 and its official MD5
`d5be2c99e436081266810594117db496`. A later firmware requires a reviewed code
and protocol update that pins its official identity, followed by the full
catalogue; an inventory author cannot self-declare a different accepted hash.

## 2. Generate the pending manifest

Create an empty evidence directory, then run:

```sh
python3 scripts/pocket_hardware_qa.py generate \
  --inventory /private/swan-song-qa/inventory.json \
  --output /private/swan-song-qa/evidence/manifest.json
```

The command hashes the inventory files and writes the complete 25-case
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

The fixed catalogue covers:

| Area | Required cases |
|---|---|
| Startup and launcher | Fresh SD, Startup Action to openFPGA, Recent creation/relaunch, last-title reuse, Reset all to defaults |
| Negative boot | Missing mono/color BIOS, too-small/non-power-of-two/oversized ROM, recovery with valid inputs |
| Disabled features | Memories rejection/unavailability, Sleep not advertised, quick-load non-mutation |
| Pocket input | Complete horizontal and vertical matrices, simultaneous directions, Start, held and latched Fast Forward, observed Controls behavior without assuming editability or persistence |
| Presentation | Auto/forced horizontal/vertical, 180-degree landscape, no input remap, transition-frame integrity |
| Display/screenshots | Raw and ares color, all LCD-response modes, generic display modes `0x20/0x30/0x40`, native 224x144 Pocket PNG, grayscale recovery |
| Dock input | Wired and wireless matrices, recorded Controls/D-pad/analog behavior, hot-unplug while held, reconnect, dedicated menu and Select+Down fallback |
| Dock video | HDMI 0/270/180-degree presentation, aspect/crop, display modes, first portrait frame, no resync |
| Negative devices | P2 gamepad, P3 keyboard, P4 mouse, disconnect, then P1 recovery |
| Save data | SRAM and EEPROM absent/create/quit/relaunch/power-cycle/flush lifecycles, exact before/after hashes |
| RTC | Epoch initialization, minute/day crossings, quit/relaunch, power cycle, title isolation, trailer hashes |
| Negative saves | Short, oversized, malformed RTC, wrong type, supported type-`0x01` canonical 32 KiB behavior, documented legacy EEPROM case, recovery |
| Audio | Pocket and Dock 48 kHz captures, stereo identity, silence, extrema, pops/drift, Fast Forward sound modes, menu transitions |
| Whole-device lifecycle | Dock/undock without reset or corruption and a minimum 120-minute stability run |

The verifier also enforces the appropriate ROM and controller class for each
case. Listing an unrelated horizontal ROM for vertical input, a Pocket control
for the wired-Dock case, or a non-RTC ROM for RTC lifecycle is rejected.

## 4. Evidence schema

The manifest envelope is `hardware_qa` with magic
`SWAN_SONG_HARDWARE_QA_EVIDENCE_V1`. Unknown or missing members fail. Its
top-level members are:

- `run_id`, `created_at`, and `operator`, copied exactly from the private
  inventory;
- `environment`, regenerated and compared byte-for-data from all inventory
  inputs on every verification;
- `artifacts`, the hashed evidence registry;
- `cases`, exactly one of every V1 case with no additions or omissions;
- `attestation`, the final physical-observation and review declaration.

Each artifact has exactly `id`, `kind`, `path`, `label`, `captured_at`, `size`,
and lowercase `sha256`. Paths are POSIX-relative to the manifest directory;
absolute paths, `..`, missing files, empty files, symlinks, repeated paths, and
hash mismatches fail. Allowed evidence kinds are:

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
ID, 25 required cases, artifact count, and the SHA-256 of the exact manifest
bytes that were parsed. It also prints that this is not mechanical proof.
Archive the private inventory and complete evidence directory together. The
manifest is not independently reproducible without the exact private firmware,
device-ID source files, core artifacts, BIOSes, and ROMs. A successful command
means the evidence record is internally consistent, not that hardware QA has
been independently certified.

## Relationship to release evidence

[`scripts/package_core.py`](scripts/package_core.py) currently records
`pocket_hardware` and `dock_hardware` as reviewed booleans in its separate
build-evidence manifest. It does not consume or hash this hardware-QA manifest.
This protocol deliberately does not modify that package code, set either gate,
authorize the publisher, alter release metadata, or create an archive.

A release reviewer may set those booleans only after this verifier succeeds for
the exact core/RBF under review and the private evidence has been inspected.
Until package evidence is explicitly extended to bind the hardware manifest's
SHA-256, preserve both records together and do not treat a boolean alone as the
underlying physical evidence.
