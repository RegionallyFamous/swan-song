# Build and Test

Swan Song treats simulation, FPGA compilation, packaging, and physical testing
as separate evidence stages. Passing an earlier stage never implies a later
one passed.

## Run the regression suite

The supported entry point is:

```sh
make regression
```

The default local simulation path requires Docker for the pinned GHDL
translation image, Verilator 5.x, a C++17 compiler, Python 3, and `tclsh`. The
regression translates the VHDL console hierarchy, compiles the Verilator
harness, executes open and generated programs, checks deterministic frame/trace
evidence, runs focused RTL and host tests, validates APF definitions, and
audits package and release contracts.

Apple-Silicon developers may explicitly substitute the caller-supplied
official `ghdl-llvm-6.0.0-macos15-aarch64` bundle for only the GHDL Docker
calls:

```sh
./scripts/with_native_macos_ghdl.sh \
  --bundle /absolute/path/to/ghdl-llvm-6.0.0-macos15-aarch64 \
  -- make regression
```

The wrapper does not download tools, accept arbitrary Docker commands, or
change CI. It uses a cleaned private temporary copy of the native driver,
LLVM backend, dump utility, and runtime library; fails closed on unsupported
images/options/paths; and removes its temporary files. This is native host
execution, not a security sandbox or a reproduction of Docker's filesystem and
network isolation. Docker remains the default and pinned Linux CI evidence.
Setup details and the exact safety boundary are in
[BUILDING.md](https://github.com/RegionallyFamous/swan-song/blob/main/BUILDING.md#optional-native-ghdl-on-macos).

The complete current result list, exact commands, trace options, and save
conversion tools are maintained in [BUILDING.md](https://github.com/RegionallyFamous/swan-song/blob/main/BUILDING.md).
Do not replace that record with a generic “tests pass” claim.

## Simulation boundary

The translated harness runs `SwanTop`, the console-level system used by both
the MiSTer and Pocket integrations. Focused SystemVerilog benches and host
contract tests cover Pocket-specific behavior around it. This provides strong,
repeatable feedback without pretending to simulate PocketOS, the scaler,
physical SDRAM timing, Dock firmware, or FPGA routing.

Structured trace tooling can record CPU, memory, DMA, display provenance, and
atomic rendered cells. It exists to answer specific implementation questions,
not to catalogue private games. See [the trace
guide](https://github.com/RegionallyFamous/swan-song/blob/main/sim/verilator/TRACE.md).

## Quartus build

The hardware target is pinned to Quartus Prime Lite 21.1.1 Build 850 on Linux.
Apple Silicon has no native Quartus build, so the supported Mac workflow uses
an isolated Linux/amd64 Docker environment and a user-supplied official 6.6 GB
archive. The archive cannot be committed, mirrored, or redistributed by this
project.

The exact archive identity, component manifest, Docker preflight, fit command,
TimeQuest evidence, and known limitations are in [Quartus on Apple Silicon
Mac](https://github.com/RegionallyFamous/swan-song/blob/main/QUARTUS_MAC_DOCKER.md)
and the [fit-evidence audit](https://github.com/RegionallyFamous/swan-song/blob/main/QUARTUS_FIT_AUDIT.md).

An optional, explicitly billable DigitalOcean launcher can create a temporary
native x86_64 worker. It is dry-run-first, restricts SSH to one `/32`, binds
the exact default-branch commit, and uses a one-job JIT GitHub runner. Each
runner gets a random per-job label whose raw nonce must exactly match the
workflow dispatch; rearm rotates it and recovery rejects mismatches. The
launcher destroys the recorded cloud resources afterward. It is a Quartus
worker, not a ROM testing server or remote ChatGPT host. Read [Swan Song
Lab](https://github.com/RegionallyFamous/swan-song/blob/main/SWAN_SONG_LAB.md)
before creating anything.

## Private ROM-corpus smoke tests

Owners may run local smoke tests against their own legally obtained images.
The private corpus stays outside the repository in a permission-restricted
folder. Public summaries use opaque identifiers and exclude filenames, raw
hashes, ROM bytes, screenshots, traces, and logs.

The local ZIP importer is dry-run by default, validates and deduplicates ROMs,
and can safely install exact-size owner-supplied mono and Color BIOS archives.
Only an explicit `--apply` writes bytes, and then only under the private lab;
no ROM or BIOS is uploaded.

Do not upload a commercial ROM or BIOS to GitHub, DigitalOcean, Railway, CI,
or a collaborator. The local runner's purpose, checks, privacy model, and
limitations are documented in [Private local ROM-corpus
testing](https://github.com/RegionallyFamous/swan-song/blob/main/PRIVATE_CORPUS_TESTING.md).

## Publish the reviewed Wiki

The pages you are reading are maintained under `docs/wiki` in the main Swan
Song repository. A guarded local command validates those pages and compares
them with an explicitly supplied clean clone of
`RegionallyFamous/swan-song.wiki`:

```sh
python3 scripts/wiki_sync.py --wiki-clone /absolute/path/to/swan-song.wiki
```

That command is an offline preview: it lists every page to add, change, or
delete and never writes or publishes. After reviewing the plan, an authorized
maintainer can use `--apply --confirm-publish
RegionallyFamous/swan-song.wiki`. The apply path rechecks the clean clone and
exact GitHub origin, commits only the planned page operations, preserves
`.git`, and pushes noninteractively. The full clone, safety, authentication,
and push-failure procedure is in
[BUILDING.md](https://github.com/RegionallyFamous/swan-song/blob/main/BUILDING.md#publishing-the-reviewed-github-wiki).

## Package and release gates

A release candidate needs all of the following:

1. clean deterministic host and RTL regression;
2. two byte-identical Quartus 21.1.1 fit and TimeQuest candidates bound to the
   same RBF/source commit by attestations from distinct signed workflow runs
   with different fresh job nonces;
3. a deterministic APF package that passes the strict package and release
   policy audits;
4. physical Pocket and Dock execution of the required lifecycle, control,
   video, audio, save, fault, and known-title matrices; and
5. explicit distribution and licensing authorization; and
6. owner-enabled GitHub immutable releases, followed by post-publication
   `gh release verify` and local-asset verification.

The checked policy intentionally leaves release authorization false until
those gates are reviewed. Do not create tags or releases simply because a ZIP
can be built.
