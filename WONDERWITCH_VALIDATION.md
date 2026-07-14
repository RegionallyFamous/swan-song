# WonderWitch compatibility validation

## Result

Swan Song now has simulation evidence for a useful, current subset of
WonderWitch: a Wonderful `wwitch` application assembled into a read-only
AthenaOS `mkrom` image boots as an ordinary `.ws` cartridge and executes BIOS
text/input services. This closes the previous “untested territory” gap for
this read-only BIOS-call fixture without claiming a writable WonderWitch
cartridge.

Wonderful's current
[WonderWitch guide](https://wonderful.asie.pl/wiki/doku.php?id=wswan%3Aguide%3Awwitch)
documents two outputs. `wf-wwitchtool mkfent` creates a traditional `.fx` file;
`wf-wwitchtool mkrom` puts one or more files into a `.ws` based on an open,
clean-room BIOS/OS. The latter is the right APF path today because Swan Song's
slot 0 already accepts `.ws`/`.wsc`, while APF has no Freya filesystem service.

The clean-room implementation is
[AthenaOS at `d37beae`](https://github.com/OpenWitch/AthenaOS/tree/d37beae7482616313883dcfa4bdb7114d1ef5749).
Its ROM-safe configuration selects simple read-only cartridge memory and does
not depend on WonderWitch's port-`CEh` flash window. Wonderful distributes that
exact source revision as `target-wswan-athenaos 0.2.0.r173.d37beae-1`.

## Reproducible run

On 2026-07-13, the checked-in source fixture was built twice with the pinned
packages and produced byte-identical `.fx` and `.ws` artifacts after its
four-byte Freya mtime normalization. The generated firmware and composite ROM
remain ignored build outputs; Swan Song does not distribute them.

```sh
make regression
scripts/validate_wonderwitch_athena.sh
```

The first command supplies the already-verified GHDL-to-Verilator system model.
The second verifies package versions and clean-room firmware hashes, rebuilds
the source fixture, checks the Athena filesystem/OS/BIOS layout, runs five
frames, and verifies the trace plus raster. It passed two consecutive runs with
the same 158 filtered application CPU events, 33,602 background-cell events,
five frame hashes, and final 238-pixel `Hello, World!` glyph raster.

The complete source, package table, artifact hashes, and observed addresses are
in
[`testroms/swan-song/wonderwitch_athena_hello/README.md`](testroms/swan-song/wonderwitch_athena_hello/README.md).
The ordinary regression runs an offline mutation test over the source identity;
the opt-in command owns the external Wonderful/Athena dependency.

## Honest boundary

Verified in the translated system model:

- current Wonderful `wwitch` compile and Freya-headered `.fx` production;
- deterministic `wf-wwitchtool mkrom --small` assembly with pinned AthenaOS;
- AthenaBIOS reset, AthenaOS boot, `rom0` executable discovery/launch;
- WonderWitch CRT transition to DS=`1000h` cartridge SRAM;
- BIOS text initialization, text output, and `key_wait`; and
- stable 224x144 visible output.

Not yet verified or implemented:

- Quartus fit/timing or Pocket/Dock execution of this image;
- direct selection of a standalone `.fx` from APF;
- writable Freya/Athena filesystem persistence;
- Bandai 2003 high-bank storage addressing beyond the current 16 MiB APF limit
  (D1/D3/D5 register semantics are mapper-tested separately);
- MBM29DL400TC flash command state or erase/program persistence (`CEh` bit 0
  and its volatile byte-wide ROM window are now mapper-tested separately); and
- serial/XMODEM development workflows on Pocket's link port.

Those are separate targets. In particular, the successful read-only `mkrom`
path is not evidence that commercial or homebrew software which self-programs a
WonderWitch flash cartridge will work.
