# Quartus 21.1.1 on an Apple-Silicon Mac

Swan Song is pinned to Quartus Prime Lite 21.1.1 Build 850 for the Pocket's
Cyclone V `5CEBA4F23C8`. Quartus has no macOS build. This workflow runs the
official Linux amd64 release in an amd64 Docker container and leaves the source
checkout read-only.

## Required download

Download exactly this file from the official
[Quartus Prime Lite 21.1.1 Linux page](https://www.altera.com/downloads/fpga-development-tools/quartus-prime-lite-edition-design-software-version-21-1-1-linux):

```text
~/Downloads/Quartus-lite-21.1.1.850-linux.tar
SHA-1: 789c1133d99fde7146fdb99c1f5dcb4d2e5cc0cc
```

The vendor lists the bundle as 6.6 GB and identifies the two files used here as:

```text
QuartusLiteSetup-21.1.1.850-linux.run
SHA-1: 6b25e8c62535d0ac02a1075b3dd334d2b04394aa

cyclonev-21.1.1.850.qdz
SHA-1: 467123b7bd5e6907beb7d6b1e073ed7bad3e5e94
```

Do not download Questa. The existing Verilator/GHDL flow supplies simulation;
Questa is not needed for synthesis, fitting, assembly, or timing analysis.

## Preflight and installation

Docker Desktop must be running. First prove that this Mac can start a pinned
Ubuntu 20.04 amd64 container:

```sh
./scripts/quartus_docker.sh doctor
```

Verify the complete vendor bundle and the two required inner packages:

```sh
./scripts/quartus_docker.sh verify
```

Read and accept the Quartus license agreement, then explicitly authorize its
unattended installer for this invocation:

```sh
QUARTUS_ACCEPT_EULA=1 ./scripts/quartus_docker.sh image
```

The image build:

1. verifies the exact outer and inner SHA-1 values;
2. exposes only the Lite installer and Cyclone V pack to the installer;
3. omits Questa, Help, and every other device pack;
4. removes the bundled Nios II tree before creating the runtime image;
5. checks Linux amd64, `21.1.1 Build 850`, `Lite Edition`, and resolves the
   exact Pocket part to `Cyclone V` using Quartus's device database.

The installer command follows Altera's documented unattended options:
`--mode unattended`, `--accept_eula 1`, and `--installdir`. The vendor's
[command-line option reference](https://www.intel.com/content/www/us/en/docs/programmable/683472/25-1/command-line-options.html)
states that EULA acceptance is mandatory in unattended mode.

### What has and has not been proved locally

The pinned Ubuntu 20.04 amd64 base and every declared Ubuntu runtime package
have been built successfully under Docker's amd64 emulation on the current Mac.
Ubuntu 20 LTS support is vendor-sourced, but Altera does not publish a complete
21.1.1 headless-container package manifest. The selected shared libraries are a
conservative CLI/installer runtime set and remain an implementation choice,
not a vendor-certified dependency list.

`/opt/intelFPGA` is an explicit local installation path supplied through the
vendor-documented `--installdir` option. The expected executable location,
`/opt/intelFPGA/quartus/bin/quartus_sh`, follows Quartus's documented Linux
layout (the vendor's
[startup guide](https://www.intel.com/content/www/us/en/docs/programmable/683472/25-1/starting-the-software.html)
places executables under `<installation-directory>/quartus/bin`). Until the
official archive is present and the image build completes, runtime dependency
sufficiency, the installer on this emulated CPU, that exact shell path, the
version/edition output, and Cyclone V device-database resolution are all
unproven. The image build fails if any one of those expectations is wrong.

## Fit and timing build

Commit all tracked source changes first. The reproducible build-ID contract
deliberately rejects a dirty tree. Then run:

```sh
./scripts/quartus_docker.sh build
```

The host checkout is mounted read-only and the container builds a fresh
`git archive` of the exact commit with its commit timestamp. Runtime networking
is disabled. The existing `scripts/build_core.sh` invokes
`quartus_sh --flow compile ap_core`, which runs synthesis, fitting, assembly,
and timing analysis.

Results are copied to:

```text
build/quartus-docker/<short-commit>/
```

A successful run requires nonempty `ap_core.rbf`, `ap_core.fit.rpt`,
`ap_core.sta.rpt`, and `ap_core.flow.rpt`. It also preserves the full
`output_files` directory, build log, toolchain version, source metadata,
generated build ID, and RBF SHA-256. A failed compile still preserves its log
and any partial reports, but returns failure and does not count as a fit/timing
pass.

To select a different empty artifact directory or local image tag:

```sh
./scripts/quartus_docker.sh build /absolute/path/to/empty-output
QUARTUS_IMAGE=my-local-tag:21.1.1 ./scripts/quartus_docker.sh check-image
```

## Licensing and platform boundary

[Altera's licensing FAQ](https://www.intel.com/content/www/us/en/support/programmable/licensing/q-and-a.html)
states that Quartus Prime Lite needs no license file. The runtime therefore
passes no license into the container and clears the common license environment
variables before compiling. EULA acceptance is still required to install and
use the software.

Ubuntu 20 LTS was added as a supported operating system for the 21.1 Standard/Lite
line, as recorded in the vendor's
[21.1 software and device support release notes](https://cdrdv2-public.intel.com/792256/rn-qts-std-dev-support-683593-792256.pdf).
The container pins the official Ubuntu 20.04 amd64 image manifest rather than a
mutable architecture-neutral tag.

Docker documents `--platform linux/amd64` as the way to run an Intel image on
Apple Silicon, but also calls this emulation
[best effort](https://docs.docker.com/desktop/troubleshoot-and-support/troubleshoot/known-issues/):
it can crash, and it is slower and more memory-intensive than native execution.
Docker likewise warns that
[QEMU builds are much slower](https://docs.docker.com/build/builders/drivers/docker-container/)
for compute-heavy compilation.

Consequently, `doctor` proves only that a basic amd64 Linux process starts.
Until the official installer, Quartus device probe, complete Swan Song fit, and
timing reports all succeed on this Mac, Quartus-under-emulation remains an
unproven host path. A successful emulated fit still does not replace testing the
RBF on an Analogue Pocket.

Finally, SHA-1 is used because it is the digest the vendor publishes for this
release. These checks detect corruption and package mix-ups against that pinned
vendor value; they are not a modern cryptographic signature.
