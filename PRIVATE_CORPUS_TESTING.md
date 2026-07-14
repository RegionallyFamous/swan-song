# Private local ROM-corpus testing

`scripts/run_private_corpus.py` is an exploratory translated-RTL smoke runner
for ROM images that the operator is permitted to test. It is deliberately
local-only: do not upload cartridge dumps, BIOS images, frames, traces, or raw
logs to Railway, GitHub Actions, or another hosted service.

By default the runner creates this owner-only lab outside the repository and
outside the normal `Documents` tree:

```text
~/Library/Application Support/Swan Song Test Lab/
├── private/
│   ├── bios/bw.rom       # exactly 4,096 bytes
│   ├── bios/color.rom    # exactly 8,192 bytes
│   ├── roms/             # uncompressed regular .ws/.wsc files only
│   ├── results/          # resumable, sanitized per-case certificates
│   └── work/             # ephemeral private ROM/BIOS copies and RGB frames
└── reports/              # sanitized import, inventory, and run summaries
```

Managed directories and a new local HMAC key are created with `0700`/`0600`
permissions. Existing permissions are never silently changed; a group- or
other-accessible input produces a path-free warning. Finder's `.DS_Store` and
AppleDouble `._*` path components are ignored, including their complete
subtrees; no other unsupported filename receives that exception. Symlinks,
archives, special files, unsupported extensions, missing or wrong-size BIOS
images, and ROMs outside 64 KiB through 16 MiB are rejected. ROMs must be
complete 64-KiB banks with a supported footer, valid additive checksum, valid
mono/Color field, supported save type and mapper, and a 16-bit bus declaration.
Compact non-power-of-two images also need a consistent declared mapper
aperture.
Any custom `--lab-root` that resolves inside this repository is rejected before
the runner creates a directory or file.

## Import owner-supplied ZIPs

`scripts/import_private_corpus.py` safely stages No-Intro-style ZIP collections
into the same lab. Dry-run is the default: it creates only the owner-only lab,
local HMAC key, and sanitized `reports/corpus-import.json`. Add `--apply` only
after reviewing its opaque counts. ROM and BIOS bytes are never written to the
repository or sent over a network.

Each ROM ZIP must contain exactly one regular `.ws` or `.wsc` member. The
importer rejects source or archive symlinks, traversal names, encrypted
members, duplicate member names, multiple regular members, unsupported
compression, excessive entry counts, compressed or expanded size limits,
unsafe expansion ratios, invalid cartridge footers, and bad cartridge
checksums. Accepted ROMs are deduplicated using the lab's secret-keyed identity
and stored under generic `rom-<opaque-id>.ws` or `.wsc` names. Reports contain
no input path, member name, title, raw content hash, or bytes.

Use explicit BIOS options to remove manual setup. The mono archive must contain
one regular 4,096-byte member and the Color archive one regular 8,192-byte
member. They are written only as `private/bios/bw.rom` and `color.rom`.

```sh
python3 scripts/import_private_corpus.py \
  "$HOME/Owned ROMs/WonderSwan" \
  "$HOME/Owned ROMs/WonderSwan Color" \
  --bios-mono "$HOME/Owned ROMs/WonderSwan/mono-bios.zip" \
  --bios-color "$HOME/Owned ROMs/WonderSwan Color/color-bios.zip"

# Repeat the identical command with --apply after the dry-run succeeds.
```

For a small known-problem pass, `--select TEXT` may be repeated, `--exclude
TEXT` removes matches, and `--limit N` caps the deterministic selection. The
terms are used only in memory and the report records only how many were
supplied. Applying is all-or-nothing when any source, archive, image, or
existing destination is rejected. Existing byte-identical opaque ROM or exact
BIOS files are accepted without rewriting; conflicting destinations fail
closed.

Inventory without executing any cartridge:

```sh
python3 scripts/run_private_corpus.py inventory
```

The equivalent run-shaped dry check is:

```sh
python3 scripts/run_private_corpus.py run --dry-run
```

The runner requires an already-built, regular, non-symlink
`build/sim/obj_dir/VSwanTop`; it never builds or writes under the repository.
Build the simulator separately using only the checked-in open fixture, then run
the six-frame corpus smoke:

```sh
./sim/verilator/run.sh \
  --rom testroms/spritepriority/spritepriority.ws \
  --frames 1 --out /tmp/swan-song-build-check

python3 scripts/run_private_corpus.py run --workers 4
```

For the confirmation pass, execute every case twice and require identical raw
frame chains:

```sh
python3 scripts/run_private_corpus.py run \
  --workers 4 --frames 60 --max-cycles 34000000 \
  --wall-timeout 90 --repeat
```

The validated footer, not the filename extension, selects the 4-KiB mono or
8-KiB Color BIOS. Each simulator process receives only a generic private copy
of its inputs. Its stdout and stderr are discarded, generated RGB files are
validated and HMACed, and the temporary directory is removed. Passing results
resume only when the simulator binary, both BIOS identities, frame/cycle/wall
limits, and repeat setting produce the same secret-keyed run contract.
Malformed resume evidence is not overwritten or accepted.

The JSON printed to stdout and written below `reports/` contains no source
path, title, raw ROM/BIOS hash, log, frame, screenshot, or trace. ROM and frame
identities are HMAC-SHA-256 values made with the local key, so they cannot be
looked up in a public ROM database without that key. A rejected entry fails the
overall command even when other cases pass; duplicate byte-identical images run
once.

This is not release evidence. It exercises the translated `SwanTop`, not the
complete APF/Pocket wrapper. The current simulator does not load or flush
cartridge saves, persist console EEPROM, provide a controlled RTC, capture
audio, reproduce Pocket video delivery/rotation, or prove physical Pocket and
Dock behavior. Original-BIOS owner setup may therefore block a title. Use
longer title-specific input routes for investigation and the documented
physical Pocket/Dock protocol for acceptance.
