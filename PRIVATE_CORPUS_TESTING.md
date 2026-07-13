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
└── reports/              # sanitized inventory and run summaries
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
