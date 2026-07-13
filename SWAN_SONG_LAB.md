# Swan Song Lab on DigitalOcean

`Swan Song Lab.command` is the Mac control surface for an ephemeral native
x86_64 Ubuntu 24.04 Quartus worker. Double-clicking it is safe: before a lab
exists it prints a dry-run plan, and afterward it prints status. It never
creates a billable resource without the explicit `launch --apply` command.

This is not a Railway service or a ChatGPT server. Codex can operate the same
local CLI through the Mac terminal after `doctl`, `gh`, and SSH are configured.
No OpenAI credential is needed or stored. The lab is a one-job GitHub JIT
self-hosted runner for `.github/workflows/quartus-fit.yml`; it has the exact
`self-hosted`, `linux`, `x64`, and `swan-song-quartus-21-1-1` labels required by
that workflow.

If desired, add a local Action in Codex desktop Settings that invokes
`Swan Song Lab.command status`; the Action and authenticated clients stay on
the Mac. Do not install Codex credentials or an experimental remote app-server
on the Droplet—the project terminal/Action invoking this CLI is the supported
control boundary.

## One-time Mac setup

Install the two authenticated clients:

```sh
brew install doctl gh
doctl auth init
gh auth login
```

Add an existing Mac SSH public key to DigitalOcean, then record its ID or
fingerprint:

```sh
doctl compute ssh-key list
```

If its private half is not one of SSH's default identity files, also pass
`--identity-file ~/.ssh/YOUR_KEY` to `launch`; the path remains local.

Download the exact official `Quartus-lite-21.1.1.850-linux.tar` archive to
`~/Downloads/` from the [Altera Quartus Prime Lite 21.1.1 Linux download](https://www.altera.com/downloads/fpga-development-tools/quartus-prime-lite-edition-design-software-version-21-1-1-linux).
The
launcher requires its pinned SHA-1
`789c1133d99fde7146fdb99c1f5dcb4d2e5cc0cc` and the existing strict component
manifest; a renamed, incomplete, or different archive fails before cloud
creation.

Find the Mac's current public IPv4 address using a service you trust and append
`/32`. The launcher accepts only a single IPv4 host route, never `0.0.0.0/0`.
If the address changes, destroy and recreate the lab with the new address.

## Launch

Preview first; this performs no network request or cloud change:

```sh
./Swan\ Song\ Lab.command launch \
  --ssh-key DIGITALOCEAN_KEY_ID_OR_FINGERPRINT \
  --ssh-cidr YOUR.PUBLIC.IPV4/32 \
  --quartus-archive ~/Downloads/Quartus-lite-21.1.1.850-linux.tar
```

After reading the vendor EULA, create the lab:

```sh
./Swan\ Song\ Lab.command launch --apply --accept-quartus-eula \
  --ssh-key DIGITALOCEAN_KEY_ID_OR_FINGERPRINT \
  --ssh-cidr YOUR.PUBLIC.IPV4/32 \
  --quartus-archive ~/Downloads/Quartus-lite-21.1.1.850-linux.tar
```

The default is DigitalOcean's `g-8vcpu-32gb` size in `nyc3` plus a 200 GiB raw
volume. Availability and at least 8 vCPUs/32 GiB RAM are verified at apply
time; `--region` and `--size` are configurable. Cloud-init refuses any existing
filesystem signature before formatting the new raw volume as ext4, then uses it
for Docker and the runner work/temp tree, satisfying the workflow's 80 GiB
free-space preflight.

Creation may take well over an hour and is billable until destroy succeeds.
As checked on 2026-07-13, the default General Purpose Droplet is
[$0.375/hour](https://www.digitalocean.com/pricing/droplets), while DigitalOcean
charges [volumes at $0.10/GiB/month](https://docs.digitalocean.com/products/volumes/details/pricing/)
with hourly accrual even while detached. The 200 GiB volume is therefore about
$20/month if forgotten. Check current pricing before apply.
Every wait and transfer is bounded. A partial failure is retained in the local
`.swan-song-lab/state.json` so exact resource IDs can be inspected and deleted.
That private-mode file contains IDs and status, never DigitalOcean, GitHub, or
JIT tokens.

Cloud-init installs rootful Docker, disables password and interactive SSH,
limits both the DigitalOcean firewall and UFW to TCP/22 from the supplied `/32`,
and allows no other public ingress. The first SSH connection uses OpenSSH
trust-on-first-use (`accept-new`) inside a dedicated per-lab `known_hosts` file;
later connections require that pinned host key. This prevents changes to the
user's global SSH host database, but it is not independent first-contact host
authentication. The launcher then:

1. verifies the official archive locally;
2. copies it directly over SSH to the attached private volume;
3. checks out the exact current commit, which must equal GitHub's current
   default-branch head;
4. verifies the archive again, builds and checks the required local-only
   `swan-song-quartus:21.1.1-850-cyclonev` image, and deletes the remote archive;
5. downloads a checksum-bound official Linux x64 Actions runner; and
6. generates a repository JIT configuration locally and starts an ephemeral
   runner that automatically deregisters after one job.

The Quartus archive and image are never pushed to a registry. The launcher does
not read, catalogue, or upload ROMs or BIOS files. Commercial ROM testing belongs
on personally controlled physical hardware, not this cloud worker.

## Codex control commands

Codex can invoke these same commands in the repository terminal:

```sh
./Swan\ Song\ Lab.command status
./Swan\ Song\ Lab.command ssh -- docker image inspect swan-song-quartus:21.1.1-850-cyclonev
./Swan\ Song\ Lab.command dispatch
./Swan\ Song\ Lab.command dispatch --apply
```

`dispatch` is a dry run unless `--apply` is present. It rechecks that the
default branch has not moved, records the exact workflow-run ID returned by
GitHub, and verifies that run's branch, commit, event, and unique dispatch nonce.
The protected `quartus-fit` GitHub environment can still require approval before
the job reaches the runner.
GitHub is the durable place for workflow logs and candidate evidence; the
Droplet remains disposable.

Destroy immediately after the job and evidence review. The first command is a
preview; the second deletes the recorded GitHub runner, Droplet, attached
volume, firewall, and tag. A queued or running recorded workflow is cancelled
and observed stopped first. Local state and the per-lab SSH host-key file are
removed only after absence is confirmed; auth, network, server, or malformed
API responses are errors rather than evidence of absence:

```sh
./Swan\ Song\ Lab.command destroy
./Swan\ Song\ Lab.command destroy --apply --confirm swan-song-quartus-lab
```

DigitalOcean documents the underlying [Droplet create](https://docs.digitalocean.com/reference/doctl/reference/compute/droplet/create/),
[volume create](https://docs.digitalocean.com/reference/doctl/reference/compute/volume/create/),
and [firewall](https://docs.digitalocean.com/reference/doctl/reference/compute/firewall/create/)
commands. GitHub documents repository
[just-in-time runner configurations](https://docs.github.com/en/rest/actions/self-hosted-runners#create-configuration-for-a-just-in-time-runner-for-a-repository)
and recommends ephemeral/JIT registration for untrusted self-hosted-runner
workloads.
