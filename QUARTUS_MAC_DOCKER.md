# Quartus 21.1.1 on an Apple-Silicon Mac

Swan Song is pinned to Quartus Prime Lite 21.1.1 Build 850 for the Pocket's
Cyclone V `5CEBA4F23C8`. Quartus has no macOS build. This workflow runs the
official Linux amd64 release in an amd64 Docker container and leaves the source
checkout read-only.

Altera now labels 21.1.1 as legacy software, recommends upgrading for current
functional and security updates, and warns that the download may eventually be
removed. Swan Song nevertheless pins this exact build because FPGA results and
their evidence must be reproducible with the project's reviewed tool version.
Do not silently substitute a newer Quartus release. See the warning and exact
legacy payload on the official
[Quartus Prime Lite 21.1.1 Linux page](https://www.altera.com/downloads/fpga-development-tools/quartus-prime-lite-edition-design-software-version-21-1-1-linux).

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
The repository's fail-closed automation requires the complete 6.6 GB archive
above even though Altera also publishes its inner installer and Cyclone V
payload separately. Keep at least 36 GB free for the archive, extracted build
context, Docker layers, Quartus installation, and compile artifacts. An 8 GB or
larger Docker VM memory allocation is a practical starting point for the fit;
that is a project recommendation, not a vendor guarantee.

## Preflight and installation

Docker Desktop must be running. First prove that this Mac can start a pinned
Ubuntu 20.04 amd64 container:

```sh
./scripts/quartus_docker.sh doctor
```

Docker's current
[Mac installation requirements](https://docs.docker.com/desktop/setup/install/mac-install/)
recommend Rosetta 2 on Apple Silicon for the best experience, but no longer
require it for Docker Desktop itself. Do not change Docker's virtual-machine
manager or Rosetta setting merely for this workflow: run `doctor` against the
current configuration, and proceed only if its amd64 probe succeeds.

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

On the current Apple-Silicon Mac, Docker Desktop 4.81.0 successfully ran the
pinned Ubuntu 20.04 amd64 image with networking disabled, and `uname -m`
returned `x86_64`. Thus the current basic `doctor` probe passes. This proves
only that a small amd64 Linux process starts; it does not prove that the much
larger Quartus installer or compiler will survive emulation.

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
Docker's current
[virtual-machine-manager documentation](https://docs.docker.com/desktop/features/vmm/)
also states that Docker VMM does not support Rosetta and therefore runs amd64
emulation slowly. Docker separately warns that
[non-native builds under QEMU user-mode emulation](https://docs.docker.com/build/building/multi-platform/)
can be much slower for compute-heavy work such as compilation. These limits are
reasons to allow extra build time and retain the native-Linux fallback, not a
requirement to alter a working Docker Desktop configuration.

Consequently, `doctor` proves only that a basic amd64 Linux process starts.
Until the official installer, Quartus device probe, complete Swan Song fit, and
timing reports all succeed on this Mac, Quartus-under-emulation remains an
unproven host path. A successful emulated fit still does not replace testing the
RBF on an Analogue Pocket.

There is no official Pocket/APF software simulator. The local Verilator and
GHDL harnesses test core logic but cannot reproduce PocketOS, the APF host,
physical SDRAM timing, the LCD/scaler/Dock path, or execute an RBF as Pocket
hardware would. After a successful fit, follow
[`POCKET_SD_STAGING.md`](POCKET_SD_STAGING.md) for the fail-closed package and
microSD workflow before hardware acceptance testing.

## Automated VM lanes

The repository already uses a fresh GitHub-hosted Ubuntu 24.04 VM on every
push and pull request. That lane verifies the immutable Verilator/GHDL
toolchain and runs `make regression`; it is the right place for open-source
simulation, synthesis smoke tests, format contracts, negative mutations, and
packaging checks that do not require Quartus.

Quartus needs a separate x86_64 Linux lane. GitHub's standard Linux runner
has only 14 GB of SSD, exactly the vendor's stated minimum for Quartus Lite
itself, before the 6.6 GB installer, Docker layers, source, and fit artifacts.
Use either an 8-vCPU/32-GB/300-GB GitHub larger runner or an ephemeral
self-hosted/cloud Ubuntu 24.04 x86_64 VM. A practical self-hosted target is 8
vCPU, 32 GB RAM, and at least 100 GB SSD. The host can stay current because the
verified Quartus container itself remains pinned to Ubuntu 20.04. The workflow
fails before checkout unless the guest reports Linux x86_64, at least 8 online
CPUs, 30 GiB of kernel-reported RAM, 80 GiB free at `RUNNER_TEMP`, a local
Unix-socket Linux/x86_64 Docker daemon, and another 80 GiB visible from the
pinned Quartus image's container layer. The two paths may share a
filesystem; both are checked because Quartus builds under container `/tmp`
while reports are copied to `RUNNER_TEMP`. Provision 32 GB/100 GB rather than
using those detection thresholds as sizing targets. These probes establish
only guest and daemon reports: they cannot identify the physical CPU or rule
out an emulated x86_64 VM, and they do not establish that this design will fit.
Provision the trusted lane on actual x86_64 hardware when predictable Quartus
runtime is required.

Use a rootful Docker Engine inside this dedicated VM. The reviewed wrapper runs
the build container as root, then uses the embedded cleanup trap to return the
artifact bind mount to the Actions runner's numeric UID/GID. Rootless Docker is
not part of the verified contract. Do not reuse this daemon or runner for
untrusted pull-request jobs.

Provision the licensed vendor archive to that VM outside Git and GitHub
caches, accept the EULA there, and build the pinned private image once. A
trusted manual or protected-branch job can then run:

```sh
python3 scripts/verify_hosted_regression.py \
  --repository "$GITHUB_REPOSITORY" \
  --sha "$GITHUB_SHA" \
  --branch "$GITHUB_REF_NAME"
./scripts/quartus_docker.sh check-image
./scripts/quartus_docker.sh build "$RUNNER_TEMP/quartus-fit"
```

The proof uses the read-only GitHub Actions API and requires the active
`.github/workflows/regression.yml` workflow's exact ID and path plus a
completed successful `push` run for the same repository, default branch, and
40-hex commit. It also fetches the exact run attempt's jobs and requires the
single GitHub-hosted Ubuntu `verilator` job plus checkout, immutable-toolchain,
and full-regression steps to have completed successfully rather than skipped.
The hosted lane already ran the complete `make regression` suite with the
pinned Verilator/GHDL toolchain, so the Quartus worker does not repeat that
roughly 18-minute gate. Missing, queued, skipped, failed, wrong-branch, or
wrong-workflow results fail closed. `GITHUB_TOKEN` is read from the environment
and needs only `actions: read`; it is never accepted on the command line.
The query uses GitHub's documented
[workflow-runs API](https://docs.github.com/en/rest/actions/workflow-runs?apiVersion=2026-03-10)
with the pinned `2026-03-10` API version.

The checked-in `.github/workflows/quartus-fit.yml` provides the manual fit
job. It will remain queued until a runner carrying the cumulative labels
`self-hosted`, `linux`, `x64`, and `swan-song-quartus-21-1-1` is online. Its
job guard accepts only the repository's default branch, the `quartus-fit`
GitHub environment requires an explicit approval, and a runtime probe
requires the guest, capacity, local-endpoint, and Docker properties above. The
source checkout is exact and credential-free; the workflow never downloads,
installs, caches, or publishes Quartus. After resolving the private image tag
once, the gate validates its exact `sha256:` image ID and runs every inspection
and fit by that immutable ID with an explicit reviewed entrypoint. The host
generates provenance outside the writable artifact bind, starts the fit with an
empty artifact directory, rejects container-created reserved provenance names,
and merges its genuine evidence only after the container exits. The evidence
records the image ID, the immutable manifest-digest portions of any registry
repo digests, and a sorted, hashed `dpkg-query` package manifest from the same
image. Registry hosts, repository names, and the requested local image tag are
deliberately discarded before public evidence is written.

Publish only the audit JSON, reports, build log, RBF SHA-256, candidate RBF,
toolchain/build-ID files, container/package manifest, and provenance metadata;
never publish the Quartus installer or private runtime image. Do not route
public pull-request code to a persistent self-hosted runner: GitHub warns that
forked PRs can execute dangerous code on that machine. Prefer an ephemeral VM,
or restrict a dedicated runner group to a trusted workflow and protected
branch/manual dispatch. Official resource and security references are
[GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners),
[larger runners](https://docs.github.com/en/actions/reference/runners/larger-runners),
[self-hosted runners](https://docs.github.com/en/actions/reference/runners/self-hosted-runners),
and [runner-group access](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/manage-access).
The workflow's collector enforces that evidence allowlist and excludes every
other Quartus output. On a public repository, assume the uploaded 14-day
evidence bundle is public to signed-in users with repository read access.

Each dispatch performs one clean synthesis, fit, assembly, and TimeQuest run,
then applies the resource/timing auditor and preserves a bounded candidate for
later comparison. It does **not** establish RBF reproducibility: Phase 0 still
requires two independent clean Quartus 21.1.1 fits of the same commit with
identical RBF hashes. The lane also cannot certify PocketOS commands, LCD/Dock
behavior, SDRAM on the actual board, or Sleep/Wake; those remain
physical-Pocket gates.

Finally, SHA-1 is used because it is the digest the vendor publishes for this
release. These checks detect corruption and package mix-ups against that pinned
vendor value; they are not a modern cryptographic signature.
