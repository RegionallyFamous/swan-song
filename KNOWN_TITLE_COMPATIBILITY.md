# Known-title Pocket and Dock acceptance

Research snapshot: 2026-07-13. The machine-readable source of truth is
[`known-title-compatibility.json`](known-title-compatibility.json). It contains
the complete prerequisites, steps, expected results, evidence minima, Pocket
and Dock result fields, and primary-source links for every case.

**Current result: all 12 commercial-title cases and all 5 open sanity cases
are pending physical Pocket/Dock execution.** No commercial ROM, ROM hash,
save, original-hardware capture, or passing result is included or implied by
this catalogue.

## Why this is a separate gate

The open regression suite proves many isolated implementation properties, but
it cannot establish compatibility with a named commercial title. Conversely,
an issue screenshot proves that somebody observed a symptom; it does not prove
what original hardware should display. This gate keeps those evidence classes
separate:

- Commercial cases use only the tester's legally obtained dump. The tester
  computes and records SHA-256 locally; the repository does not prescribe or
  publish a commercial ROM identity.
- Every commercial scenario requires a local video of the
  same title revision on original WonderSwan hardware. MiSTer, Mednafen, issue
  images, and another Pocket core can be diagnostic comparisons but cannot be
  the correct-output reference.
- Each case is run independently on Pocket and Dock. A result is `pending`,
  `pass`, or `fail`; `fail` is valid completed evidence but cannot satisfy
  release acceptance.
- Reports that omit exact menu inputs set `operator_steps_required: true`.
  The operator must record the exact button sequence, save/new-game state,
  character/course selection, and timing used. The catalogue does not invent
  those missing facts.
- A pass requires the exact reviewed scenario list, core commit, raw-RBF hash,
  official firmware 2.6.0, hardware revisions, immutable artifact hashes, and
  a physical-observation attestation. Simulation results cannot fill hardware
  fields.
- Pocket and Dock artifacts must be captured inside that mode's declared test
  interval. Original-hardware reference captures may precede either mode run,
  but must fall between creation of the compatibility run and its latest
  completed mode; timestamps outside those windows fail validation.
- `video` and `reference_video` artifacts must use MP4, MOV, MKV, or WebM
  extensions and matching container signatures. Renamed text or arbitrary
  bytes cannot satisfy a video-evidence minimum.

## Commercial compatibility matrix

The MiSTer issues below were still open on the research date. The Pocket save
issues have different states, noted in the table. “Expected” is deliberately
stronger than “the issue did not happen once”: it requires the specified
repeat, lifecycle, or reference comparison in the JSON catalogue.

| Title / case | Primary-source defect | Required run and expected result | Reference / evidence |
| --- | --- | --- | --- |
| Chou Denki Card Battle: Youfu Makai (Rev 3) | [MiSTer #3](https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/3) documents a crash after entering gameplay and pressing Left twice; a later report says the in-game Initialization option changes the result. | Run both clean/uninitialized and explicitly initialized paths. Both must survive two Left presses; Initialization cannot be a prerequisite for play. | Same-revision original cartridge, two videos per Pocket/Dock mode, run log. The issue reporter's published SHA-1 is not copied into the acceptance identity. |
| Meta Communication | [MiSTer #4](https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/4) says “Meta comm - Flickering in name select,” with no route or reference. | Record the exact route, hold the name selector, and traverse every position at a controlled rate. Output must match original hardware without core-only flicker. | Same-revision original hardware; video and run log per mode. |
| Star Hearts Taikenban / Trial | [MiSTer #4](https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/4) reports rain-overlay flicker. | Record the exact route to one rain scene and capture the unobstructed overlay for at least twenty seconds. It must match the same trial build on original hardware. | Trial-version cartridge reference; video and log per mode. Retail Star Hearts is not a substitute. |
| Final Lap 2000 (WS) | [MiSTer #4](https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/4) uses the shorthand “Final Lap” for track flicker; [MiSTer #30](https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/30) explicitly identifies the WS title Final Lap 2000 and shows a bad England GP start line. | On one owner-identified Final Lap 2000 dump, complete a recorded circuit and capture the England GP start-line crossing. Track layers and start line must match hardware. | Same-revision cartridge reference for both scenarios; two videos and a log per mode. One SHA-256 binds the one source-identified title. |
| One Piece: Grand Battle Swan Colosseum | [MiSTer #2](https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/2) reports special-move garbage; its [follow-up](https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/2#issuecomment-877572178) adds a character-transition line glitch and unstable health bars while jumping. | Record exact fighters, stage, move, and inputs; repeat character transitions, isolated jumps, and one special move under fixed conditions. All three scenes must match hardware. | Same-revision cartridge; one video per scenario plus log, in each mode. |
| Makaimura | [MiSTer #12](https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/12) reports a wrong leftmost column when post-death map scrolling starts. A [comment](https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/12#issuecomment-1101961578) reproduces it in MiSTer and Mednafen but explicitly leaves real-hardware behavior unresolved. | Lose exactly one life, capture the immediately following map and its first scroll at high frame rate, and compare frame by frame. | An original monochrome WonderSwan capture is mandatory. Emulator agreement does not decide pass or fail. |
| Romancing SaGa (Japan) | [MiSTer #15](https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/15) shows lower-corner sprites blinking during text boxes. | Record the exact path to the matched dialogue, hold the page, then advance ten pages at a fixed rate. Corner sprites must match hardware. | Same-revision original hardware; video and log per mode. |
| Digimon Battle Spirit 1.5 | [MiSTer #24](https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/24) reports a brief corrupt VS scale-in and corruption after rapid Up/Down while paused. | Capture five identical VS entrances; separately pause a fixed fight, alternate Up/Down exactly twenty times, and resume. Both paths must match hardware. | Same-revision original hardware; two videos and a log per mode. |
| Super Robot Wars Compact for WonderSwan Color | [MiSTer #25](https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/25) and mirrored [Pocket #7](https://github.com/agg23/openfpga-wonderswan/issues/7) report black horizontal lines in battle without a complete reproduction route. | Record the exact battle, units, commands, and animation; repeat the same attack three times. No core-only black lines may appear. | Same-revision original hardware; video and log per mode. |
| Engacho! | Closed [Pocket #3](https://github.com/agg23/openfpga-wonderswan/issues/3) documents EEPROM progress disappearing after leaving the core. The reporter later [confirmed](https://github.com/agg23/openfpga-wonderswan/issues/3#issuecomment-1535654039) both new saves and cartridge-dumped saves worked in the 1.0.1 beta. | Solve puzzle 1, prove puzzle 2 is available, quit/relaunch, switch titles, and cold boot. Puzzle 2 must remain available and save hashes must change only at valid in-game writes. | Owner cartridge on original hardware; two lifecycle videos, at least three save snapshots, and log per mode. No upstream save is imported. |
| Another Heaven: Memory of Those Days | The detailed [Pocket #3 report](https://github.com/agg23/openfpga-wonderswan/issues/3#issuecomment-1514058112) says Continue disappeared after a core exit; the same [1.0.1 retest](https://github.com/agg23/openfpga-wonderswan/issues/3#issuecomment-1535654039) confirmed persistence. | Create a manual save, prove Continue locally, quit/relaunch and load it, save again, switch titles, and cold boot. Continue and the intended scene must survive. | Owner cartridge on original hardware; two videos, three save snapshots, and log per mode. |
| Stock-header Star Hearts | Closed-as-not-actionable [Pocket #2](https://github.com/agg23/openfpga-wonderswan/issues/2) gives exact steps to the first save and documents a corruption prompt/wipe when writes exceed the header-declared SRAM size. | Use the unpatched owner dump, obtain the weapon and drum, save via Y1, then test relaunch, title switch, and cold boot. The save and protection bytes must survive without a wipe prompt. | Stock same-revision cartridge; two videos, four save snapshots, and log per mode. A header-patched ROM does not exercise this case. |

## Open and generated sanity matrix

These are redistributable, hash-bound fixtures and are intentionally outside
the commercial-title pass count. Their source-defined terminal markers make
excellent Pocket/Dock smoke tests, but none may be cited as proof that a
commercial title works.

| Fixture | Checked-in identity and expected hardware screen | Scope boundary |
| --- | --- | --- |
| `ws-test-suite` 80186 quirks | [`80186_quirks.ws`](testroms/ws-test-suite/80186_quirks/README.md), SHA-256 `b440…eb1c`; three PASS markers | AAM/AAD base 16 and SALC value behavior only |
| `ws-test-suite` SoC interrupts | [`interrupts.ws`](testroms/ws-test-suite/interrupts/README.md), SHA-256 `d8a4…47da`; thirteen PASS markers | Source-defined interrupt-controller cases only |
| `ws-test-suite` internal EEPROM | [`internal.ws`](testroms/ws-test-suite/internal_eeprom/README.md), SHA-256 `2e5c…3db`; twenty-three mono-hardware PASS markers | Internal EEPROM protocol, not cartridge EEPROM persistence |
| Shift-JIS / Misaki glyph fixture | [`sjis_glyph_provenance.wsc`](testroms/swan-song/sjis_glyph_provenance/README.md), SHA-256 `b199…fa`; six documented glyphs | Licensed controlled glyph path, not a commercial text renderer |
| Wonderful medium-SRAM probe | [`medium_sram_probe.wsc`](testroms/swan-song/wonderful_medium_sram/README.md), SHA-256 `b7f6…34aa`; `MEDIUM-SRAM OK` | Rebuildable 32-KiB SRAM/runtime path, not Star Hearts protection |

The validator recomputes every full fixture SHA-256 from the checked-in file;
the shortened values above are labels only.

## Recording and validation workflow

1. Validate the untouched pending catalogue:

   ```sh
   python3 scripts/known_title_compatibility.py
   ```

2. Copy `known-title-compatibility.json` outside the repository or into an
   ignored private evidence directory. Fill `run`, the owner-computed
   commercial `owner_rom_sha256` values, exact `operator_steps`, original
   hardware reference data, per-mode results, and the artifact index. Do not
   put commercial ROMs, saves, or private captures in the project tree.

3. Validate an in-progress manifest. Pending modes are allowed, but completed
   modes must already meet all identity, procedure, and artifact rules:

   ```sh
   python3 scripts/known_title_compatibility.py \
     --manifest private-known-title-run/manifest.json
   ```

4. Require every Pocket and Dock run to be complete, including failing runs:

   ```sh
   python3 scripts/known_title_compatibility.py \
     --manifest private-known-title-run/manifest.json \
     --require-complete
   ```

5. Use the release gate only when every mode is an evidenced pass:

   ```sh
   python3 scripts/known_title_compatibility.py \
     --manifest private-known-title-run/manifest.json \
     --require-pass
   ```

The validator rejects missing or reordered cases, altered procedures,
non-SHA-256 commercial identities, wrong firmware/core identities, absent or
tampered files, unsafe paths, reused/unreferenced artifacts, insufficient
per-case evidence, out-of-window evidence timestamps, missing original-hardware
references, pending modes, failed modes under `--require-pass`, and
simulation-derived attestations. It cannot
prove that a human label is truthful, so independent review remains required.
