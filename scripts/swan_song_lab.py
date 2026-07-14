#!/usr/bin/env python3
"""Fail-closed DigitalOcean control surface for an ephemeral Quartus runner."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from typing import Any, Sequence
from urllib.parse import quote

import verify_hosted_regression as regression_proof


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / ".swan-song-lab" / "state.json"
ARCHIVE_NAME = "Quartus-lite-21.1.1.850-linux.tar"
ARCHIVE_SHA1 = "789c1133d99fde7146fdb99c1f5dcb4d2e5cc0cc"
IMAGE = "swan-song-quartus:21.1.1-850-cyclonev"
LABELS = ["self-hosted", "linux", "x64", "swan-song-quartus-21-1-1"]
JOB_LABEL_PREFIX = "swan-song-job-"
OUTBOUND_RULES = (
    "protocol:tcp,ports:0,address:0.0.0.0/0 "
    "protocol:udp,ports:0,address:0.0.0.0/0 "
    "protocol:icmp,ports:0,address:0.0.0.0/0"
)
MAGIC = "SWAN_SONG_DIGITALOCEAN_LAB_V1"
DEFAULT_REPO = "RegionallyFamous/swan-song"
DEFAULT_IMAGE = "ubuntu-24-04-x64"
DEFAULT_SIZE = "g-8vcpu-32gb"
DEFAULT_REGION = "nyc3"
DEFAULT_VOLUME_GIB = 200
COMMAND_TIMEOUT = 120
CREATE_WAIT_SECONDS = 600
SSH_WAIT_SECONDS = 900
BUILD_TIMEOUT = 3 * 60 * 60
COPY_TIMEOUT = 2 * 60 * 60


class LabError(RuntimeError):
    """The requested lab operation could not be completed safely."""


def run(
    argv: Sequence[str],
    *,
    input_text: str | None = None,
    timeout: int = COMMAND_TIMEOUT,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(argv),
            input=input_text,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise LabError(f"command failed or timed out: {shlex.join(argv)}: {error}") from error
    if check and result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic"
        raise LabError(f"command failed: {shlex.join(argv)}: {detail}")
    return result


def json_command(argv: Sequence[str], *, input_body: Any | None = None) -> Any:
    result = run(
        argv,
        input_text=None if input_body is None else json.dumps(input_body),
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise LabError(f"command returned invalid JSON: {shlex.join(argv)}") from error


def one_object(value: Any, label: str) -> dict[str, Any]:
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if not isinstance(value, dict):
        raise LabError(f"{label} did not return exactly one object")
    return value


def validate_slug(value: str, label: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}[a-z0-9]", value):
        raise LabError(f"{label} must contain only lowercase letters, digits, and hyphens")
    return value


def validate_repo(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise LabError("repository must be OWNER/REPO")
    return value


def validate_ssh_cidr(value: str) -> str:
    try:
        network = ipaddress.ip_network(value, strict=True)
    except ValueError as error:
        raise LabError("--ssh-cidr must be the Mac's public IPv4 address followed by /32") from error
    if network.version != 4 or network.prefixlen != 32:
        raise LabError("--ssh-cidr must restrict SSH to one public IPv4 address (/32)")
    return str(network)


def validate_commit(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise LabError("the lab source ref must resolve to a full lowercase 40-hex commit")
    return value


def validate_lab_nonce(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise LabError("lab nonce must be exactly 32 lowercase hexadecimal characters")
    return value


def new_lab_nonce(previous: str | None = None) -> str:
    nonce = validate_lab_nonce(uuid.uuid4().hex)
    if previous is not None and nonce == validate_lab_nonce(previous):
        raise LabError("refusing to reuse the prior one-job lab nonce")
    return nonce


def install_lab_nonce(state: dict[str, Any], nonce: str) -> None:
    nonce = validate_lab_nonce(nonce)
    resource_names = state.setdefault("resource_names", {})
    if not isinstance(resource_names, dict):
        raise LabError("recorded resource names are invalid")
    state["lab_nonce"] = nonce
    resource_names["workflow_run"] = nonce


def state_lab_nonce(state: dict[str, Any]) -> str:
    nonce = validate_lab_nonce(state.get("lab_nonce"))
    resource_names = state.get("resource_names")
    if not isinstance(resource_names, dict):
        raise LabError("recorded resource names are invalid")
    if resource_names.get("workflow_run") != nonce:
        raise LabError("recorded lab nonce and workflow-run nonce do not match")
    return nonce


def recorded_workflow_branch(state: dict[str, Any]) -> str:
    """Return the exact branch used by the recorded one-shot workflow."""
    branch = state.get("workflow_branch", state.get("default_branch"))
    if not isinstance(branch, str) or not re.fullmatch(r"[A-Za-z0-9._/-]+", branch):
        raise LabError("recorded workflow branch is missing or unsafe")
    return branch


def recorded_workflow_profile(state: dict[str, Any]) -> str:
    """Keep older candidate-only state files forward compatible."""
    profile = state.get("workflow_profile", "candidate")
    if profile not in {"candidate", "connectivity-refresh"}:
        raise LabError("recorded workflow profile is invalid")
    return profile


def recorded_workflow_commit(state: dict[str, Any]) -> str:
    """Return the checked-out source commit, independent of the warm image."""
    commit = state.get("workflow_commit", state.get("commit"))
    if not isinstance(commit, str):
        raise LabError("recorded workflow commit is missing")
    return validate_commit(commit)


def recorded_workflow_display_title(state: dict[str, Any]) -> str:
    """Accept the one recorded pre-raw-nonce run, never an arbitrary title."""
    nonce = state_lab_nonce(state)
    modern = f"Quartus fit candidate {nonce}"
    legacy = state.get("legacy_workflow_display_title")
    if legacy is None:
        return modern
    expected_legacy = f"Quartus fit candidate swan-lab-{nonce}"
    if legacy != expected_legacy:
        raise LabError("recorded legacy workflow title does not match the lab nonce")
    return expected_legacy


def branch_api_path(repo: str, branch: str) -> str:
    return f"repos/{repo}/branches/{quote(branch, safe='')}"


def jit_labels(state: dict[str, Any]) -> list[str]:
    return [*LABELS, f"{JOB_LABEL_PREFIX}{state_lab_nonce(state)}"]


def runner_label_names(runner: dict[str, Any]) -> list[str]:
    labels = runner.get("labels")
    if not isinstance(labels, list):
        raise LabError("GitHub runner response has no valid labels")
    names: list[str] = []
    for label in labels:
        name = label.get("name") if isinstance(label, dict) else label
        if not isinstance(name, str) or not name:
            raise LabError("GitHub runner response has an invalid label")
        names.append(name)
    return names


def validate_runner_identity(runner: Any, state: dict[str, Any]) -> int:
    if not isinstance(runner, dict) or not isinstance(runner.get("id"), int):
        raise LabError("GitHub runner response has no runner ID")
    if runner.get("name") != state.get("runner_name"):
        raise LabError("GitHub runner response does not match the planned runner name")
    expected = jit_labels(state)
    names = runner_label_names(runner)
    dynamic = [name for name in names if name.startswith(JOB_LABEL_PREFIX)]
    if dynamic != [expected[-1]]:
        raise LabError("GitHub runner response does not have the exact one-job nonce label")
    if len(names) != len(expected) or {name.casefold() for name in names} != {
        name.casefold() for name in expected
    }:
        raise LabError("GitHub runner response does not have the exact planned labels")
    return runner["id"]


def state_path(args: argparse.Namespace) -> Path:
    return Path(args.state).expanduser().resolve()


def load_state(path: Path, *, required: bool = True) -> dict[str, Any] | None:
    if not path.exists():
        if required:
            raise LabError(f"no lab state at {path}; run launch first")
        return None
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise LabError(f"lab state is not a regular, non-symlink file: {path}")
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LabError(f"could not read lab state: {path}") from error
    if not isinstance(body, dict) or body.get("magic") != MAGIC:
        raise LabError(f"unrecognized lab state: {path}")
    return body


def save_state(path: Path, body: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise LabError(f"lab state directory must not be a symlink: {path.parent}")
    descriptor, temporary_name = tempfile.mkstemp(prefix="state.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            json.dump(body, target, sort_keys=True, indent=2)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def create_private_empty_file(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise LabError(f"refusing to reuse existing SSH host-key file: {path}")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as error:
        raise LabError(f"could not create private SSH host-key file: {path}") from error
    os.close(descriptor)


def require_tools() -> None:
    for tool in ("doctl", "gh", "ssh", "scp", "ssh-keygen", "git", "python3"):
        result = run(["/usr/bin/env", "sh", "-c", f"command -v {tool}"], check=False)
        if result.returncode:
            raise LabError(f"required local command is missing: {tool}")
    run(["doctl", "account", "get", "--output", "json"])
    run(["gh", "auth", "status", "--hostname", "github.com"])


def local_commit(ref: str | None) -> str:
    expression = "HEAD^{commit}" if ref is None else f"{ref}^{{commit}}"
    return validate_commit(run(["git", "rev-parse", "--verify", expression]).stdout.strip())


def verify_archive(path: Path) -> None:
    if path.name != ARCHIVE_NAME or not path.is_file() or path.is_symlink():
        raise LabError(f"--quartus-archive must be a regular file named {ARCHIVE_NAME}")
    run(["python3", str(ROOT / "scripts" / "quartus_archive.py"), "verify", str(path)], timeout=600)


def cloud_init(volume_name: str, ssh_cidr: str) -> str:
    device = f"/dev/disk/by-id/scsi-0DO_Volume_{volume_name}"
    return f"""#!/bin/bash
set -euo pipefail
exec > >(tee -a /var/log/swan-song-lab-bootstrap.log) 2>&1
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl docker.io git jq make perl python3 rsync tcl ufw
install -d -m 0755 /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/00-swan-song-lab.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
X11Forwarding no
AllowTcpForwarding no
EOF
sshd -t
systemctl reload ssh
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow from {ssh_cidr} to any port 22 proto tcp
ufw --force enable
for attempt in $(seq 1 120); do
  [[ -b {shlex.quote(device)} ]] && break
  sleep 2
done
[[ -b {shlex.quote(device)} ]]
if blkid {shlex.quote(device)} >/dev/null 2>&1; then
  echo "refusing to format a volume that already has a filesystem signature" >&2
  exit 1
fi
mkfs.ext4 -F {shlex.quote(device)}
test "$(blkid -o value -s TYPE {shlex.quote(device)})" = ext4
systemctl stop docker.service docker.socket containerd.service || true
install -d -m 0755 /srv/swan-song-data /var/lib/docker
mount -o defaults,nofail,discard,noatime {shlex.quote(device)} /srv/swan-song-data
uuid="$(blkid -o value -s UUID {shlex.quote(device)})"
printf 'UUID=%s /srv/swan-song-data ext4 defaults,nofail,discard,noatime 0 2\n' "$uuid" >> /etc/fstab
install -d -m 0711 /srv/swan-song-data/docker
install -d -m 0711 /srv/swan-song-data/containerd
mount --bind /srv/swan-song-data/docker /var/lib/docker
printf '/srv/swan-song-data/docker /var/lib/docker none bind 0 0\n' >> /etc/fstab
install -d -m 0755 /etc/containerd
cat > /etc/containerd/config.toml <<'EOF'
version = 2
root = "/srv/swan-song-data/containerd"
EOF
install -d -m 0755 /etc/systemd/system/containerd.service.d
cat > /etc/systemd/system/containerd.service.d/swan-song-storage.conf <<'EOF'
[Unit]
RequiresMountsFor=/srv/swan-song-data
EOF
systemctl daemon-reload
systemctl enable --now containerd.service docker.service
docker info >/dev/null
useradd --create-home --shell /bin/bash runner
usermod -aG docker runner
install -d -o runner -g runner -m 0750 /srv/swan-song-data/runner-work
install -d -m 0700 /srv/swan-song-data/incoming /srv/swan-song-data/tmp
touch /var/lib/cloud/instance/swan-song-lab-ready
"""


def ssh_target(state: dict[str, Any]) -> str:
    address = state.get("public_ip")
    if not isinstance(address, str) or not address:
        raise LabError("lab state has no public IPv4 address")
    return f"root@{address}"


def ssh_base(state: dict[str, Any]) -> list[str]:
    command = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=15",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
    ]
    if state.get("known_hosts_file"):
        command.extend(["-o", f"UserKnownHostsFile={state['known_hosts_file']}"])
    if state.get("identity_file"):
        command.extend(["-i", state["identity_file"]])
    command.append(ssh_target(state))
    return command


def key_material(value: str) -> str:
    fields = value.strip().split()
    if len(fields) < 2:
        raise LabError("SSH public key has no algorithm and encoded key material")
    return " ".join(fields[:2])


def select_identity_file(args: argparse.Namespace, digitalocean_key: dict[str, Any]) -> None:
    expected = digitalocean_key.get("public_key")
    if not isinstance(expected, str):
        raise LabError("DigitalOcean SSH-key response omitted public key material")
    candidates: list[Path] = []
    if args.identity_file:
        candidates.append(Path(args.identity_file).expanduser().resolve())
    else:
        home = Path.home() / ".ssh"
        candidates.extend(home / name for name in ("id_ed25519", "id_ecdsa", "id_rsa"))
    matches: list[Path] = []
    for candidate in candidates:
        if not candidate.is_file() or candidate.is_symlink():
            continue
        result = run(["ssh-keygen", "-y", "-f", str(candidate)], check=False)
        if result.returncode == 0 and key_material(result.stdout) == key_material(expected):
            matches.append(candidate)
    if len(matches) != 1:
        raise LabError(
            "could not match the selected DigitalOcean SSH key to exactly one local private key; "
            "pass --identity-file"
        )
    args.identity_file = str(matches[0])


def wait_for_droplet(state: dict[str, Any]) -> None:
    deadline = time.monotonic() + CREATE_WAIT_SECONDS
    while time.monotonic() < deadline:
        body = one_object(
            json_command(["doctl", "compute", "droplet", "get", str(state["droplet_id"]), "--output", "json"]),
            "droplet",
        )
        if body.get("status") == "active" and body.get("networks"):
            networks = body.get("networks", {}).get("v4", [])
            addresses = [entry.get("ip_address") for entry in networks if entry.get("type") == "public"]
            if addresses and isinstance(addresses[0], str):
                state["public_ip"] = addresses[0]
                return
        time.sleep(5)
    raise LabError("bounded wait expired before the Droplet became active")


def wait_for_ssh(state: dict[str, Any]) -> None:
    deadline = time.monotonic() + SSH_WAIT_SECONDS
    command = ssh_base(state) + ["test -f /var/lib/cloud/instance/swan-song-lab-ready"]
    while time.monotonic() < deadline:
        if not run(command, timeout=30, check=False).returncode:
            return
        time.sleep(10)
    raise LabError("bounded wait expired before secure cloud-init completed")


def preflight_apply(args: argparse.Namespace) -> tuple[Path, str]:
    require_tools()
    repo = validate_repo(args.repo)
    repository = one_object(json_command(["gh", "api", f"repos/{repo}"]), "GitHub repository")
    default_branch = repository.get("default_branch")
    if not isinstance(default_branch, str) or not re.fullmatch(r"[A-Za-z0-9._/-]+", default_branch):
        raise LabError("GitHub repository has no safe default-branch name")
    args.default_branch = default_branch
    archive = Path(args.quartus_archive).expanduser().resolve()
    verify_archive(archive)
    commit = local_commit(args.ref)
    branch = one_object(
        json_command(["gh", "api", f"repos/{repo}/branches/{default_branch}"]),
        "GitHub default branch",
    )
    remote_commit = branch.get("commit", {}).get("sha") if isinstance(branch.get("commit"), dict) else None
    if remote_commit != commit:
        raise LabError("the exact local source commit must equal the current GitHub default-branch head")
    key = one_object(
        json_command(["doctl", "compute", "ssh-key", "get", args.ssh_key, "--output", "json"]),
        "SSH key",
    )
    if not (key.get("fingerprint") or key.get("id")):
        raise LabError("DigitalOcean did not return the requested existing SSH key")
    select_identity_file(args, key)
    sizes = json_command(["doctl", "compute", "size", "list", "--output", "json"])
    if not isinstance(sizes, list):
        raise LabError("DigitalOcean size inventory is invalid")
    matching = [entry for entry in sizes if entry.get("slug") == args.size]
    if len(matching) != 1:
        raise LabError(f"DigitalOcean size is unavailable: {args.size}")
    size = matching[0]
    if size.get("available") is not True:
        raise LabError(f"DigitalOcean size is currently unavailable: {args.size}")
    if int(size.get("vcpus", 0)) < 8 or int(size.get("memory", 0)) < 32768:
        raise LabError("DigitalOcean size must provide at least 8 vCPUs and 32 GiB RAM")
    if args.region not in size.get("regions", []):
        raise LabError(f"DigitalOcean size {args.size} is not available in {args.region}")
    image = one_object(
        json_command(["doctl", "compute", "image", "get", args.image, "--output", "json"]),
        "Ubuntu image",
    )
    if (
        image.get("slug") != DEFAULT_IMAGE
        or image.get("distribution") != "Ubuntu"
        or image.get("public") is not True
        or "24.04" not in str(image.get("name", ""))
        or "x64" not in str(image.get("name", ""))
    ):
        raise LabError("the requested image is not the official public Ubuntu 24.04 x64 image")
    return archive, commit


def plan(args: argparse.Namespace) -> None:
    archive = args.quartus_archive or f"~/Downloads/{ARCHIVE_NAME}"
    key = args.ssh_key or "<existing DigitalOcean SSH key ID or fingerprint>"
    cidr = args.ssh_cidr or "<your Mac public IPv4>/32"
    print("Swan Song Lab plan (no cloud or network changes were made)")
    print(f"  repository: {args.repo}")
    print(f"  Droplet: Ubuntu 24.04 x86_64, {args.size}, {args.region}")
    print(f"  attached volume: {args.volume_gib} GiB ext4")
    print(f"  SSH key: {key}")
    print(f"  local private key: {args.identity_file or 'SSH default identity files'}")
    print(f"  SSH ingress: TCP/22 from {cidr} only; all other public ingress denied")
    print(f"  Quartus input: {archive} (pinned SHA-1 {ARCHIVE_SHA1})")
    print(f"  required local Docker image before runner registration: {IMAGE}")
    print(
        f"  GitHub JIT labels: {', '.join(LABELS)}, "
        f"{JOB_LABEL_PREFIX}<fresh 32-lowercase-hex nonce>"
    )
    print("  ROM/BIOS policy: never uploaded by this launcher")
    print("  lifecycle: launch --apply, dispatch --apply, destroy --apply --confirm NAME")
    print("BILLING WARNING: apply creates a billable Droplet and volume until destroy succeeds.")


def prepare_remote(state: dict[str, Any], archive: Path, commit: str) -> None:
    remote_archive = f"/srv/swan-song-data/incoming/{ARCHIVE_NAME}"
    scp = [
        "scp", "-q",
        "-o", "BatchMode=yes",
        "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-o", f"UserKnownHostsFile={state['known_hosts_file']}",
    ]
    if state.get("identity_file"):
        scp.extend(["-i", state["identity_file"]])
    scp.extend([str(archive), f"{ssh_target(state)}:{remote_archive}"])
    run(scp, timeout=COPY_TIMEOUT)
    repo_url = f"https://github.com/{state['repo']}.git"
    remote = f"""set -euo pipefail
archive={shlex.quote(remote_archive)}
cleanup() {{
  status=$?
  trap - EXIT
  if ! rm -f "$archive"; then
    printf 'could not remove the remote Quartus archive\n' >&2
    (( status != 0 )) || status=1
  fi
  exit "$status"
}}
trap cleanup EXIT
test "$(sha1sum "$archive" | awk '{{print $1}}')" = {ARCHIVE_SHA1}
rm -rf /srv/swan-song-source
git clone --filter=blob:none --no-checkout {shlex.quote(repo_url)} /srv/swan-song-source
cd /srv/swan-song-source
git fetch --depth=1 origin {commit}
git checkout --detach {commit}
test "$(git rev-parse HEAD)" = {commit}
python3 scripts/quartus_archive.py verify "$archive"
export TMPDIR=/srv/swan-song-data/tmp
export QUARTUS_ACCEPT_EULA=1
build_log=/srv/swan-song-data/quartus-image-build.log
umask 077
: > "$build_log"
set +e
./scripts/quartus_docker.sh image "$archive" > "$build_log" 2>&1
build_status=$?
set -e
if (( build_status != 0 )); then
  printf 'Quartus image build failed with status %s; tail follows:\n' "$build_status" >&2
  tail -c 65536 "$build_log" >&2 || true
  exit "$build_status"
fi
./scripts/quartus_docker.sh check-image
docker image inspect --format '{{{{.Id}}}}' {shlex.quote(IMAGE)}
rm -f "$build_log"
"""
    run(ssh_base(state) + ["bash", "-s"], input_text=remote, timeout=BUILD_TIMEOUT)


def runner_download(repo: str) -> tuple[str, str]:
    body = json_command(["gh", "api", f"repos/{repo}/actions/runners/downloads"])
    if not isinstance(body, list):
        raise LabError("GitHub runner download inventory is invalid")
    matches = [item for item in body if item.get("os") == "linux" and item.get("architecture") == "x64"]
    if len(matches) != 1:
        raise LabError("GitHub did not return exactly one Linux x64 runner package")
    url = matches[0].get("download_url")
    checksum = matches[0].get("sha256_checksum")
    if not isinstance(url, str) or not url.startswith("https://github.com/actions/runner/releases/download/"):
        raise LabError("GitHub runner download URL is outside the expected official origin")
    if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", checksum):
        raise LabError("GitHub runner package has no valid SHA-256 checksum")
    return url, checksum.lower()


def install_runner(state: dict[str, Any]) -> None:
    url, checksum = runner_download(state["repo"])
    remote = f"""set -euo pipefail
rm -rf /opt/actions-runner
install -d -o runner -g runner -m 0755 /opt/actions-runner
curl --fail --location --proto '=https' --tlsv1.2 {shlex.quote(url)} -o /tmp/actions-runner.tar.gz
test "$(sha256sum /tmp/actions-runner.tar.gz | awk '{{print $1}}')" = {checksum}
tar -xzf /tmp/actions-runner.tar.gz -C /opt/actions-runner
rm -f /tmp/actions-runner.tar.gz
/opt/actions-runner/bin/installdependencies.sh
ln -s /srv/swan-song-data/runner-work /opt/actions-runner/_work
chown -R runner:runner /opt/actions-runner /srv/swan-song-data/runner-work
"""
    run(ssh_base(state) + ["bash", "-s"], input_text=remote, timeout=900)


def register_runner(state: dict[str, Any], path: Path) -> None:
    if state.get("runner_id") or "runner" in state.get("pending_resources", []):
        raise LabError("refusing to reuse or retry a recorded or uncertain JIT runner registration")
    labels = jit_labels(state)
    mark_pending(state, path, "runner")
    request = {
        "name": state["runner_name"],
        "runner_group_id": 1,
        "labels": labels,
        "work_folder": "_work",
    }
    response = one_object(
        json_command(
            ["gh", "api", "--method", "POST", f"repos/{state['repo']}/actions/runners/generate-jitconfig", "--input", "-"],
            input_body=request,
        ),
        "GitHub JIT runner configuration",
    )
    runner = response.get("runner")
    config = response.get("encoded_jit_config")
    runner_id = validate_runner_identity(runner, state)
    if not isinstance(config, str) or not config or len(config) > 65536:
        raise LabError("GitHub JIT response has no bounded encoded configuration")
    state["runner_id"] = runner_id
    clear_pending(state, path, "runner")
    save_state(path, state)
    remote = f"""set -euo pipefail
install -d -o runner -g runner -m 0700 /run/swan-song-runner
umask 077
printf '%s' {shlex.quote(config)} > /run/swan-song-runner/jit
chown runner:runner /run/swan-song-runner/jit
cat > /opt/actions-runner/run-jit.sh <<'EOF'
#!/bin/bash
set -euo pipefail
config="$(cat /run/swan-song-runner/jit)"
rm -f /run/swan-song-runner/jit
exec /opt/actions-runner/run.sh --jitconfig "$config"
EOF
chmod 0755 /opt/actions-runner/run-jit.sh
chown runner:runner /opt/actions-runner/run-jit.sh
cat > /etc/systemd/system/swan-song-runner.service <<'EOF'
[Unit]
Description=Swan Song ephemeral GitHub Actions runner
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=simple
User=runner
Group=runner
SupplementaryGroups=docker
WorkingDirectory=/opt/actions-runner
ExecStart=/opt/actions-runner/run-jit.sh
Restart=no
PrivateTmp=yes
NoNewPrivileges=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now swan-song-runner.service
"""
    try:
        run(ssh_base(state) + ["bash", "-s"], input_text=remote, timeout=120)
    except Exception:
        run(
            ["gh", "api", "--method", "DELETE", f"repos/{state['repo']}/actions/runners/{state['runner_id']}"],
            check=False,
        )
        raise


def mark_pending(state: dict[str, Any], path: Path, kind: str) -> None:
    pending = state.setdefault("pending_resources", [])
    if kind not in pending:
        pending.append(kind)
    save_state(path, state)


def clear_pending(state: dict[str, Any], path: Path, kind: str) -> None:
    state["pending_resources"] = [item for item in state.get("pending_resources", []) if item != kind]
    save_state(path, state)


def object_list(argv: list[str], label: str) -> list[dict[str, Any]]:
    body = json_command(argv)
    if not isinstance(body, list) or any(not isinstance(item, dict) for item in body):
        raise LabError(f"{label} inventory is invalid")
    return body


def recover_pending(state: dict[str, Any], path: Path) -> None:
    """Reconcile a create call whose response may have been lost."""
    for kind in list(state.get("pending_resources", [])):
        name = state.get("resource_names", {}).get(kind)
        if not isinstance(name, str) or not name:
            raise LabError(f"cannot reconcile uncertain {kind}: exact planned name is missing")
        found_identifier: Any | None = None
        matches: list[dict[str, Any]] = []
        if kind == "tag":
            found = resource_get(["doctl", "compute", "tag", "get", name])
            if found is None:
                raise LabError(
                    f"uncertain tag {name} is not visible yet; retry destroy before removing local state"
                )
            state["tag_created"] = True
        elif kind == "firewall":
            matches = [item for item in object_list(
                ["doctl", "compute", "firewall", "list", "--output", "json"], "firewall"
            ) if item.get("name") == name]
            if len(matches) > 1:
                raise LabError(f"cannot reconcile uncertain firewall: multiple exact names {name}")
            if not matches:
                raise LabError(
                    f"uncertain firewall {name} is not visible yet; retry destroy before removing local state"
                )
            found_identifier = matches[0].get("id") or matches[0].get("uuid")
            state["firewall_id"] = found_identifier
        elif kind == "volume":
            matches = [item for item in object_list(
                ["doctl", "compute", "volume", "list", "--output", "json"], "volume"
            ) if item.get("name") == name]
            if len(matches) > 1:
                raise LabError(f"cannot reconcile uncertain volume: multiple exact names {name}")
            if not matches:
                raise LabError(
                    f"uncertain volume {name} is not visible yet; retry destroy before removing local state"
                )
            found_identifier = matches[0].get("id")
            state["volume_id"] = found_identifier
        elif kind == "droplet":
            matches = [item for item in object_list(
                ["doctl", "compute", "droplet", "list", "--output", "json"], "Droplet"
            ) if item.get("name") == name]
            if len(matches) > 1:
                raise LabError(f"cannot reconcile uncertain Droplet: multiple exact names {name}")
            if not matches:
                raise LabError(
                    f"uncertain Droplet {name} is not visible yet; retry destroy before removing local state"
                )
            found_identifier = matches[0].get("id")
            state["droplet_id"] = found_identifier
        elif kind == "runner":
            body = json_command(["gh", "api", f"repos/{state['repo']}/actions/runners"])
            runners = body.get("runners") if isinstance(body, dict) else None
            if not isinstance(runners, list):
                raise LabError("GitHub runner inventory is invalid")
            matches = [item for item in runners if isinstance(item, dict) and item.get("name") == name]
            if len(matches) > 1:
                raise LabError(f"cannot reconcile uncertain runner: multiple exact names {name}")
            if not matches:
                raise LabError(
                    f"uncertain runner {name} is not visible yet; retry destroy before removing local state"
                )
            found_identifier = validate_runner_identity(matches[0], state)
            state["runner_id"] = found_identifier
        elif kind == "workflow_run":
            nonce = state_lab_nonce(state)
            if name != nonce:
                raise LabError("cannot reconcile workflow run with a mismatched lab nonce")
            body = json_command([
                "gh", "api",
                f"repos/{state['repo']}/actions/workflows/quartus-fit.yml/runs?event=workflow_dispatch&per_page=100",
            ])
            runs = body.get("workflow_runs") if isinstance(body, dict) else None
            if not isinstance(runs, list):
                raise LabError("GitHub workflow-run inventory is invalid")
            matches = [
                item for item in runs
                if isinstance(item, dict)
                and item.get("display_title") == recorded_workflow_display_title(state)
                and item.get("head_sha") == recorded_workflow_commit(state)
                and item.get("head_branch") == recorded_workflow_branch(state)
                and item.get("event") == "workflow_dispatch"
            ]
            if len(matches) > 1:
                raise LabError(f"cannot reconcile uncertain workflow run: multiple nonce matches {name}")
            if not matches:
                raise LabError(
                    "workflow dispatch outcome remains uncertain; no nonce match is visible yet; "
                    "retry destroy before removing local state"
                )
            found_identifier = matches[0].get("id")
            state["workflow_run_id"] = found_identifier
        else:
            raise LabError(f"cannot reconcile unknown pending resource kind: {kind}")
        if kind != "tag" and not found_identifier:
            raise LabError(f"reconciled {kind} has no resource ID")
        clear_pending(state, path, kind)
    save_state(path, state)


def wait_runner_online(state: dict[str, Any]) -> None:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        runner = resource_get(["gh", "api", f"repos/{state['repo']}/actions/runners/{state['runner_id']}"])
        if runner is not None:
            runner_id = validate_runner_identity(runner, state)
            if runner_id != state["runner_id"]:
                raise LabError("online runner ID does not match the recorded JIT runner")
            if runner.get("status") == "online":
                return
        time.sleep(5)
    raise LabError("bounded wait expired before the JIT runner became online")


def launch(args: argparse.Namespace) -> None:
    validate_repo(args.repo)
    if args.repo != DEFAULT_REPO:
        raise LabError(f"the trusted Quartus lane is bound to {DEFAULT_REPO}")
    validate_slug(args.name, "lab name")
    validate_slug(args.region, "region")
    validate_slug(args.size, "size")
    validate_slug(args.image, "image")
    if args.volume_gib < 200:
        raise LabError("the Quartus lab volume must be at least 200 GiB")
    if not args.apply:
        plan(args)
        return
    if load_state(state_path(args), required=False) is not None:
        raise LabError("a lab state already exists; inspect status or destroy it first")
    if not args.ssh_key or not args.ssh_cidr or not args.quartus_archive:
        raise LabError("apply requires --ssh-key, --ssh-cidr, and --quartus-archive")
    if not args.accept_quartus_eula:
        raise LabError("read the Quartus EULA, then pass --accept-quartus-eula")
    args.ssh_cidr = validate_ssh_cidr(args.ssh_cidr)
    archive, commit = preflight_apply(args)
    path = state_path(args)
    suffix = hashlib.sha256(f"{args.name}:{commit}".encode()).hexdigest()[:10]
    tag = f"swan-song-lab-{suffix}"
    volume_name = f"{args.name}-{suffix}-data"
    firewall_name = f"{args.name}-{suffix}-ssh"
    nonce = new_lab_nonce()
    state: dict[str, Any] = {
        "magic": MAGIC,
        "phase": "creating",
        "name": args.name,
        "repo": args.repo,
        "commit": commit,
        "default_branch": args.default_branch,
        "region": args.region,
        "size": args.size,
        "image": args.image,
        "volume_gib": args.volume_gib,
        "ssh_cidr": args.ssh_cidr,
        "identity_file": args.identity_file,
        "tag": tag,
        "runner_name": f"{args.name}-{suffix}",
        "lab_nonce": nonce,
        "known_hosts_file": str(path.parent / "known_hosts"),
        "resource_names": {
            "tag": tag,
            "firewall": firewall_name,
            "volume": volume_name,
            "droplet": f"{args.name}-{suffix}",
            "runner": f"{args.name}-{suffix}",
            "workflow_run": nonce,
        },
        "pending_resources": [],
    }
    save_state(path, state)
    known_hosts = Path(state["known_hosts_file"])
    create_private_empty_file(known_hosts)
    print("BILLABLE APPLY: creating a Droplet and volume; destroy them explicitly when finished.")
    try:
        mark_pending(state, path, "tag")
        run(["doctl", "compute", "tag", "create", tag])
        state["tag_created"] = True
        clear_pending(state, path, "tag")
        save_state(path, state)
        mark_pending(state, path, "firewall")
        firewall = one_object(
            json_command([
                "doctl", "compute", "firewall", "create",
                "--name", firewall_name,
                "--tag-names", tag,
                "--inbound-rules", f"protocol:tcp,ports:22,address:{args.ssh_cidr}",
                "--outbound-rules", OUTBOUND_RULES,
                "--output", "json",
            ]),
            "firewall",
        )
        state["firewall_id"] = firewall.get("id") or firewall.get("uuid")
        if not state["firewall_id"]:
            raise LabError("DigitalOcean firewall response has no ID")
        clear_pending(state, path, "firewall")
        save_state(path, state)
        mark_pending(state, path, "volume")
        volume = one_object(
            json_command([
                "doctl", "compute", "volume", "create", volume_name,
                "--region", args.region,
                "--size", f"{args.volume_gib}GiB",
                "--tag", tag,
                "--output", "json",
            ]),
            "volume",
        )
        state["volume_id"] = volume.get("id")
        if not state["volume_id"]:
            raise LabError("DigitalOcean volume response has no ID")
        clear_pending(state, path, "volume")
        save_state(path, state)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix="swan-song-cloud-init-", delete=False) as user_data:
            os.fchmod(user_data.fileno(), 0o600)
            user_data.write(cloud_init(volume_name, args.ssh_cidr))
            user_data_path = Path(user_data.name)
        try:
            mark_pending(state, path, "droplet")
            droplet = one_object(
                json_command([
                    "doctl", "compute", "droplet", "create", f"{args.name}-{suffix}",
                    "--region", args.region,
                    "--size", args.size,
                    "--image", args.image,
                    "--ssh-keys", args.ssh_key,
                    "--tag-names", tag,
                    "--volumes", str(state["volume_id"]),
                    "--enable-monitoring",
                    "--enable-private-networking",
                    "--user-data-file", str(user_data_path),
                    "--output", "json",
                ]),
                "droplet",
            )
        finally:
            user_data_path.unlink(missing_ok=True)
        state["droplet_id"] = droplet.get("id")
        if not state["droplet_id"]:
            raise LabError("DigitalOcean Droplet response has no ID")
        clear_pending(state, path, "droplet")
        save_state(path, state)
        wait_for_droplet(state)
        save_state(path, state)
        wait_for_ssh(state)
        state["phase"] = "preparing-quartus"
        save_state(path, state)
        prepare_remote(state, archive, commit)
        state["phase"] = "installing-runner"
        save_state(path, state)
        install_runner(state)
        register_runner(state, path)
        wait_runner_online(state)
        state["phase"] = "ready"
        save_state(path, state)
    except Exception as error:
        state["phase"] = "failed"
        state["failure"] = str(error)
        save_state(path, state)
        raise LabError(f"launch stopped safely; run status, then destroy: {error}") from error
    print(f"Swan Song Lab is ready at {ssh_target(state)}")
    print("The one-job JIT runner is online; use dispatch --apply when ready.")


def resource_get(argv: list[str]) -> dict[str, Any] | None:
    command = list(argv)
    if command and command[0] == "doctl":
        command.extend(["--output", "json"])
    result = run(command, check=False)
    if result.returncode:
        diagnostic = (result.stderr + "\n" + result.stdout).strip()
        explicit_404 = bool(re.search(
            r"\bHTTP\s+404\b|:\s*404\s*\(request\b",
            diagnostic,
            flags=re.IGNORECASE,
        ))
        for candidate in (result.stdout, result.stderr):
            try:
                error_body = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(error_body, dict) and str(error_body.get("status")) == "404":
                explicit_404 = True
        if explicit_404:
            return None
        raise LabError(f"resource lookup failed and absence is unconfirmed: {diagnostic or shlex.join(command)}")
    try:
        return one_object(json.loads(result.stdout), "resource")
    except (json.JSONDecodeError, LabError) as error:
        raise LabError(f"resource lookup returned invalid JSON: {shlex.join(command)}") from error


def prove_hosted_regression(state: dict[str, Any]) -> dict[str, Any]:
    """Require a hosted regression success bound to this exact prepared source."""
    repository = state.get("repo")
    commit = state.get("commit")
    branch = state.get("default_branch")
    try:
        regression_proof.verify_regression_workflow_source()
        regression_proof.validate_repository(repository)
        regression_proof.validate_sha(commit)
        regression_proof.validate_branch(branch)
        api_prefix = [
            "gh",
            "api",
            "--header",
            f"X-GitHub-Api-Version: {regression_proof.API_VERSION}",
        ]
        metadata = json_command(
            api_prefix + [regression_proof.workflow_endpoint(repository)]
        )
        workflow_id = regression_proof.verify_workflow_metadata(metadata)
        runs = json_command(
            api_prefix
            + [
                regression_proof.workflow_runs_endpoint(
                    repository,
                    workflow_id,
                    commit,
                    branch,
                )
            ]
        )
        proven = regression_proof.verify_workflow_runs(
            runs,
            repository=repository,
            workflow_id=workflow_id,
            sha=commit,
            branch=branch,
        )
        jobs = json_command(
            api_prefix
            + [
                regression_proof.workflow_jobs_endpoint(
                    repository,
                    int(proven["id"]),
                    int(proven["run_attempt"]),
                )
            ]
        )
        job = regression_proof.verify_workflow_jobs(
            jobs,
            run_id=int(proven["id"]),
            sha=commit,
        )
    except regression_proof.ProofError as error:
        raise LabError(f"hosted regression proof failed: {error}") from error
    result = dict(proven)
    result["job_id"] = job["id"]
    return result


def status(args: argparse.Namespace) -> None:
    state = load_state(state_path(args))
    assert state is not None
    require_tools()
    print(f"lab: {state['name']} ({state.get('phase', 'unknown')})")
    print(f"source: {state['repo']}@{state['commit']}")
    if any(key in state for key in ("workflow_profile", "workflow_branch", "workflow_commit")):
        print(
            "workflow: "
            f"{recorded_workflow_profile(state)} "
            f"{recorded_workflow_branch(state)}@{recorded_workflow_commit(state)}"
        )
    droplet = None
    if state.get("droplet_id"):
        droplet = resource_get(["doctl", "compute", "droplet", "get", str(state["droplet_id"])])
    print(f"droplet: {droplet.get('status') if droplet else 'absent'} id={state.get('droplet_id', '-')}")
    print(f"address: {state.get('public_ip', '-')}; SSH allowed only from {state['ssh_cidr']}")
    volume = None
    if state.get("volume_id"):
        volume = resource_get(["doctl", "compute", "volume", "get", str(state["volume_id"])])
    print(f"volume: {'present' if volume else 'absent'} id={state.get('volume_id', '-')}")
    firewall = None
    if state.get("firewall_id"):
        firewall = resource_get(["doctl", "compute", "firewall", "get", str(state["firewall_id"])])
    print(f"firewall: {'present' if firewall else 'absent'} id={state.get('firewall_id', '-')}")
    runner_status = "absent"
    if state.get("runner_id"):
        runner = resource_get(["gh", "api", f"repos/{state['repo']}/actions/runners/{state['runner_id']}"])
        if runner:
            runner_status = f"{runner.get('status', 'unknown')}, busy={runner.get('busy', False)}"
    print(f"JIT runner: {runner_status} id={state.get('runner_id', '-')}")
    if state.get("workflow_run_id"):
        workflow = resource_get([
            "gh", "api", f"repos/{state['repo']}/actions/runs/{state['workflow_run_id']}"
        ])
        workflow_status = workflow.get("status", "unknown") if workflow else "absent"
        print(f"workflow run: {workflow_status} id={state['workflow_run_id']}")
    if state.get("pending_resources"):
        print("uncertain create responses: " + ", ".join(state["pending_resources"]))
    if state.get("failure"):
        print(f"last failure: {state['failure']}")


def ssh_command(args: argparse.Namespace) -> None:
    state = load_state(state_path(args))
    assert state is not None
    command = ssh_base(state)
    remote_command = list(args.command)
    if remote_command[:1] == ["--"]:
        remote_command.pop(0)
    if remote_command:
        command.extend(remote_command)
    result = subprocess.run(command, check=False)
    if result.returncode:
        raise LabError(f"SSH exited with status {result.returncode}")


def resume(args: argparse.Namespace) -> None:
    path = state_path(args)
    state = load_state(path)
    assert state is not None
    if not args.apply:
        print("Would re-verify the existing Quartus image and continue with runner installation.")
        print("No remote or GitHub state was changed. Re-run resume with --apply.")
        return
    if state.get("phase") not in ("preparing-quartus", "installing-runner", "failed"):
        raise LabError("resume requires a lab stopped during Quartus preparation")
    if state.get("runner_id") or state.get("pending_resources"):
        raise LabError("resume refuses a lab with a recorded or uncertain runner/resource operation")
    require_tools()
    branch = one_object(
        json_command(["gh", "api", f"repos/{state['repo']}/branches/{state['default_branch']}"]),
        "GitHub default branch",
    )
    branch_commit = branch.get("commit", {}).get("sha") if isinstance(branch.get("commit"), dict) else None
    if branch_commit != state["commit"]:
        raise LabError("default-branch head moved; the warm image cannot resume this prepared commit")
    remote = f"""set -euo pipefail
cd /srv/swan-song-source
test "$(git rev-parse HEAD)" = {state['commit']}
./scripts/quartus_docker.sh check-image
docker image inspect --format '{{{{.Id}}}}' {shlex.quote(IMAGE)}
"""
    run(ssh_base(state) + ["bash", "-s"], input_text=remote, timeout=900)
    resource_names = state.get("resource_names")
    has_top_nonce = "lab_nonce" in state
    has_workflow_nonce = isinstance(resource_names, dict) and "workflow_run" in resource_names
    if has_top_nonce or has_workflow_nonce:
        state_lab_nonce(state)
    else:
        install_lab_nonce(state, new_lab_nonce())
    state["phase"] = "installing-runner"
    state.pop("failure", None)
    save_state(path, state)
    try:
        install_runner(state)
        register_runner(state, path)
        wait_runner_online(state)
        state["phase"] = "ready"
        save_state(path, state)
    except Exception as error:
        state["phase"] = "failed"
        state["failure"] = str(error)
        save_state(path, state)
        raise LabError(f"resume stopped safely; run status before retrying or destroying: {error}") from error
    print("Swan Song Lab resumed from its verified image; the one-job JIT runner is online.")


def warm_storage(args: argparse.Namespace) -> None:
    state = load_state(state_path(args))
    assert state is not None
    if not args.apply:
        print("Would move containerd's warm image store onto the attached 200-GiB volume.")
        print("No service, mount, or file was changed. Re-run warm-storage with --apply.")
        return
    require_tools()
    if state.get("runner_id"):
        runner = resource_get([
            "gh", "api", f"repos/{state['repo']}/actions/runners/{state['runner_id']}"
        ])
        if runner is not None:
            raise LabError("warm-storage refuses to stop Docker while the recorded runner still exists")
    if state.get("workflow_run_id"):
        workflow = resource_get([
            "gh", "api", f"repos/{state['repo']}/actions/runs/{state['workflow_run_id']}"
        ])
        if workflow is not None and workflow.get("status") != "completed":
            raise LabError("warm-storage refuses to stop Docker while the Quartus workflow is active")
    remote = f"""set -euo pipefail
source=/var/lib/containerd
destination=/srv/swan-song-data/containerd
config=/etc/containerd/config.toml
expected_root='root = "/srv/swan-song-data/containerd"'
mountpoint -q /srv/swan-song-data
volume_available_kib="$(df -Pk /srv/swan-song-data | awk 'NR == 2 {{ print $4; exit }}')"
test "$volume_available_kib" -ge $((80 * 1024 * 1024))
install -d -m 0755 /etc/systemd/system/containerd.service.d
cat > /etc/systemd/system/containerd.service.d/swan-song-storage.conf <<'EOF'
[Unit]
RequiresMountsFor=/srv/swan-song-data
EOF
systemctl daemon-reload
if test -f "$config" && ! grep -Fqx "$expected_root" "$config"; then
  echo 'refusing to replace an unowned containerd configuration' >&2
  exit 70
fi
if ! test -f "$config"; then
  test -d "$source"
  install -d -m 0711 "$destination"
  restore_services() {{
    systemctl stop docker.service docker.socket containerd.service || true
    rm -f "$config"
    systemctl start containerd.service docker.service || true
  }}
  trap restore_services EXIT
  systemctl stop docker.service docker.socket containerd.service
  rsync -aHAX --numeric-ids --delete "$source/" "$destination/"
  install -d -m 0755 /etc/containerd
  config_temp="$(mktemp /etc/containerd/config.toml.XXXXXX)"
  printf 'version = 2\n%s\n' "$expected_root" > "$config_temp"
  chmod 0644 "$config_temp"
  mv "$config_temp" "$config"
  containerd --config "$config" config dump >/dev/null
  systemctl start containerd.service docker.service
  trap - EXIT
fi
systemctl start containerd.service docker.service
systemctl is-active --quiet containerd.service docker.service
grep -Fqx "$expected_root" "$config"
available_kib="$(df -Pk "$destination" | awk 'NR == 2 {{ print $4; exit }}')"
test "$available_kib" -ge $((80 * 1024 * 1024))
docker image inspect {shlex.quote(IMAGE)} >/dev/null
docker run --rm --platform linux/amd64 --network none --entrypoint /bin/df \
  {shlex.quote(IMAGE)} -Pk / | awk 'NR == 2 {{ exit !($4 >= 80 * 1024 * 1024) }}'
"""
    run(ssh_base(state) + ["bash", "-s"], input_text=remote, timeout=1800)
    print("containerd warm image storage is mounted on the attached volume and has at least 80 GiB free.")


def rearm(args: argparse.Namespace) -> None:
    path = state_path(args)
    state = load_state(path)
    assert state is not None
    if not args.apply:
        print("Would verify the completed run, reuse the warm Quartus image, and register one fresh JIT runner.")
        print("No remote or GitHub state was changed. Re-run rearm with --apply.")
        return
    if state.get("repo") != DEFAULT_REPO:
        raise LabError(f"the trusted Quartus lane is bound to {DEFAULT_REPO}")
    if state.get("phase") != "dispatched":
        raise LabError("rearm requires a dispatched lab whose one-job workflow has completed")
    if state.get("pending_resources"):
        raise LabError("rearm refuses a lab with an uncertain resource operation")
    resource_names = state.get("resource_names", {})
    if not isinstance(resource_names, dict):
        raise LabError("recorded resource names are invalid")
    history = state.get("completed_workflow_runs", [])
    if not isinstance(history, list):
        raise LabError("recorded completed-workflow history is invalid")
    run_id = state.get("workflow_run_id")
    runner_id = state.get("runner_id")
    if not isinstance(run_id, int) or not isinstance(runner_id, int):
        raise LabError("rearm requires the exact prior workflow and JIT runner IDs")
    old_nonce = state_lab_nonce(state)
    require_tools()
    workflow = resource_get(["gh", "api", f"repos/{state['repo']}/actions/runs/{run_id}"])
    prior_branch = recorded_workflow_branch(state)
    prior_commit = recorded_workflow_commit(state)
    prior_title = recorded_workflow_display_title(state)
    if (
        workflow is None
        or workflow.get("status") != "completed"
        or workflow.get("head_sha") != prior_commit
        or workflow.get("head_branch") != prior_branch
        or workflow.get("event") != "workflow_dispatch"
        or workflow.get("display_title") != prior_title
    ):
        raise LabError("the prior workflow is not an exact completed run for this lab")
    if resource_get(["gh", "api", f"repos/{state['repo']}/actions/runners/{runner_id}"]) is not None:
        raise LabError("the prior JIT runner still exists; rearm will not create a second runner")
    target_commit = local_commit(args.ref)
    branch = one_object(
        json_command(["gh", "api", f"repos/{state['repo']}/branches/{state['default_branch']}"]),
        "GitHub default branch",
    )
    branch_commit = branch.get("commit", {}).get("sha") if isinstance(branch.get("commit"), dict) else None
    if branch_commit != target_commit:
        raise LabError("the exact local rearm commit must equal the current GitHub default-branch head")
    repo_url = f"https://github.com/{state['repo']}.git"
    remote = f"""set -euo pipefail
cd /srv/swan-song-source
test "$(git remote get-url origin)" = {shlex.quote(repo_url)}
test -z "$(git status --porcelain)"
previous_commit="$(git rev-parse HEAD)"
restore_previous() {{
  status=$?
  trap - EXIT
  if (( status != 0 )); then
    git checkout --detach "$previous_commit" >/dev/null 2>&1 || true
  fi
  exit "$status"
}}
trap restore_previous EXIT
git fetch --depth=1 origin {target_commit}
git checkout --detach {target_commit}
test "$(git rev-parse HEAD)" = {target_commit}
test -z "$(git status --porcelain)"
./scripts/quartus_docker.sh check-image
docker image inspect --format '{{{{.Id}}}}' {shlex.quote(IMAGE)}
trap - EXIT
"""
    run(ssh_base(state) + ["bash", "-s"], input_text=remote, timeout=900)
    history.append({
        "id": run_id,
        "commit": prior_commit,
        "branch": prior_branch,
        "profile": recorded_workflow_profile(state),
        "conclusion": workflow.get("conclusion"),
        "url": state.get("workflow_run_url"),
    })
    state["completed_workflow_runs"] = history[-20:]
    nonce = new_lab_nonce(old_nonce)
    suffix = uuid.uuid4().hex[:8]
    state["runner_name"] = f"swan-rearm-{target_commit[:8]}-{suffix}"
    state["resource_names"] = resource_names
    resource_names["runner"] = state["runner_name"]
    install_lab_nonce(state, nonce)
    state["commit"] = target_commit
    state["phase"] = "installing-runner"
    state.pop("runner_id", None)
    state.pop("workflow_run_id", None)
    state.pop("workflow_run_url", None)
    state.pop("workflow_branch", None)
    state.pop("workflow_commit", None)
    state.pop("workflow_profile", None)
    state.pop("legacy_workflow_display_title", None)
    state.pop("failure", None)
    save_state(path, state)
    try:
        install_runner(state)
        register_runner(state, path)
        wait_runner_online(state)
        state["phase"] = "ready"
        save_state(path, state)
    except Exception as error:
        state["phase"] = "failed"
        state["failure"] = str(error)
        save_state(path, state)
        raise LabError(f"rearm stopped safely; inspect status before retrying or destroying: {error}") from error
    print("Warm Quartus lab rearmed; one fresh JIT runner is online and ready for dispatch.")


def dispatch(args: argparse.Namespace) -> None:
    path = state_path(args)
    state = load_state(path)
    assert state is not None
    nonce = state_lab_nonce(state) if args.apply else None
    profile = getattr(args, "profile", "candidate")
    branch = getattr(args, "ref", None) or state.get("default_branch")
    refresh_sha = getattr(args, "connectivity_refresh_sha", None)
    if profile not in {"candidate", "connectivity-refresh"}:
        raise LabError("workflow profile must be candidate or connectivity-refresh")
    if not isinstance(branch, str) or not re.fullmatch(r"[A-Za-z0-9._/-]+", branch):
        raise LabError("workflow branch is missing or unsafe")
    if profile == "candidate":
        if branch != state.get("default_branch"):
            raise LabError("candidate profile must run on the GitHub default branch")
        if refresh_sha not in (None, ""):
            raise LabError("candidate profile cannot carry a connectivity refresh SHA")
        workflow_commit = validate_commit(state.get("commit", ""))
    else:
        if not branch.startswith("codex/connectivity-refresh-"):
            raise LabError(
                "connectivity-refresh profile requires a codex/connectivity-refresh-* branch"
            )
        if not isinstance(refresh_sha, str):
            raise LabError("connectivity refresh SHA must be an explicit full commit")
        workflow_commit = validate_commit(refresh_sha)
    if not args.apply:
        print(
            f"Would dispatch .github/workflows/quartus-fit.yml profile {profile} "
            f"on {state['repo']} branch {branch}."
        )
        print("No workflow was dispatched. Re-run with --apply after status shows the runner online.")
        return
    assert nonce is not None
    if state.get("phase") != "ready" or not state.get("runner_id"):
        raise LabError("the prepared JIT runner is not ready")
    if state.get("workflow_run_id"):
        run_id = state["workflow_run_id"]
        workflow = resource_get(["gh", "api", f"repos/{state['repo']}/actions/runs/{run_id}"])
        if (
            workflow is None
            or workflow.get("head_sha") != recorded_workflow_commit(state)
            or workflow.get("head_branch") != recorded_workflow_branch(state)
            or workflow.get("event") != "workflow_dispatch"
            or workflow.get("display_title") != f"Quartus fit candidate {nonce}"
        ):
            raise LabError("the recorded workflow run does not match this prepared lab")
        state["phase"] = "dispatched"
        save_state(path, state)
        print(f"Adopted exact Quartus fit workflow run {run_id} after verified dispatch response.")
        return
    if "workflow_run" in state.get("pending_resources", []):
        raise LabError("this one-job lab already has a recorded or uncertain workflow dispatch")
    require_tools()
    remote_branch = one_object(
        json_command(["gh", "api", branch_api_path(state["repo"], branch)]),
        "GitHub workflow branch",
    )
    branch_commit = (
        remote_branch.get("commit", {}).get("sha")
        if isinstance(remote_branch.get("commit"), dict)
        else None
    )
    if branch_commit != workflow_commit:
        raise LabError("workflow branch does not equal the exact requested workflow commit")
    if profile == "candidate":
        proven_regression = prove_hosted_regression(state)
        state["hosted_regression_run_id"] = proven_regression["id"]
    else:
        state.pop("hosted_regression_run_id", None)
    state["workflow_branch"] = branch
    state["workflow_commit"] = workflow_commit
    state["workflow_profile"] = profile
    mark_pending(state, path, "workflow_run")
    inputs = {"profile": profile, "lab_nonce": nonce}
    if profile == "connectivity-refresh":
        inputs["connectivity_refresh_sha"] = refresh_sha
    response = one_object(
        json_command(
            [
                "gh", "api", "--method", "POST",
                "--header", "X-GitHub-Api-Version: 2026-03-10",
                f"repos/{state['repo']}/actions/workflows/quartus-fit.yml/dispatches",
                "--input", "-",
            ],
            input_body={
                "ref": branch,
                "inputs": inputs,
                "return_run_details": True,
            },
        ),
        "workflow dispatch",
    )
    run_id = response.get("workflow_run_id")
    if not isinstance(run_id, int):
        raise LabError("workflow dispatch response omitted its exact run ID")
    state["workflow_run_id"] = run_id
    state["workflow_run_url"] = response.get("html_url")
    clear_pending(state, path, "workflow_run")
    workflow = resource_get(["gh", "api", f"repos/{state['repo']}/actions/runs/{run_id}"])
    if (
        workflow is None
        or workflow.get("head_sha") != workflow_commit
        or workflow.get("head_branch") != branch
        or workflow.get("event") != "workflow_dispatch"
        or workflow.get("display_title") != f"Quartus fit candidate {nonce}"
    ):
        cancel_workflow_run(state)
        raise LabError("dispatched workflow did not bind the prepared commit, branch, event, and nonce")
    state["phase"] = "dispatched"
    save_state(path, state)
    print(f"Quartus fit workflow dispatched as run {run_id}; protected-environment approval may be required.")


def cancel_workflow_run(state: dict[str, Any]) -> None:
    run_id = state.get("workflow_run_id")
    if not run_id:
        return
    endpoint = f"repos/{state['repo']}/actions/runs/{run_id}"
    workflow = resource_get(["gh", "api", endpoint])
    if workflow is None or workflow.get("status") == "completed":
        return
    result = run(["gh", "api", "--method", "POST", f"{endpoint}/cancel"], check=False)
    if result.returncode:
        workflow = resource_get(["gh", "api", endpoint])
        if workflow is None or workflow.get("status") == "completed":
            return
        raise LabError(
            "could not cancel the recorded workflow run: "
            + (result.stderr.strip() or result.stdout.strip() or "no diagnostic")
        )
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        workflow = resource_get(["gh", "api", endpoint])
        if workflow is None or workflow.get("status") == "completed":
            return
        time.sleep(5)
    raise LabError("bounded wait expired before the recorded workflow run stopped")


def delete_and_confirm(
    get_argv: list[str],
    delete_argv: list[str],
    errors: list[str],
    label: str,
    *,
    wait_seconds: int = 180,
) -> None:
    if resource_get(get_argv) is None:
        return
    result = run(delete_argv, check=False)
    if result.returncode:
        if resource_get(get_argv) is None:
            return
        errors.append(f"{label}: {result.stderr.strip() or result.stdout.strip() or 'delete failed'}")
        return
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if resource_get(get_argv) is None:
            return
        time.sleep(5)
    errors.append(f"{label}: bounded deletion wait expired; absence is unconfirmed")


def destroy(args: argparse.Namespace) -> None:
    path = state_path(args)
    state = load_state(path)
    assert state is not None
    if not args.apply:
        print(f"Would delete only the IDs in {path} for lab {state['name']}:")
        print(f"  runner={state.get('runner_id', '-')} droplet={state.get('droplet_id', '-')}")
        print(f"  volume={state.get('volume_id', '-')} firewall={state.get('firewall_id', '-')} tag={state.get('tag', '-')}")
        print(f"  workflow_run={state.get('workflow_run_id', '-')} pending={state.get('pending_resources', [])}")
        print(f"No resources were deleted. Use --apply --confirm {state['name']}")
        return
    if args.confirm != state["name"]:
        raise LabError(f"destroy requires --confirm {state['name']}")
    require_tools()
    recover_pending(state, path)
    cancel_workflow_run(state)
    errors: list[str] = []
    if state.get("runner_id"):
        delete_and_confirm(
            ["gh", "api", f"repos/{state['repo']}/actions/runners/{state['runner_id']}"],
            ["gh", "api", "--method", "DELETE", f"repos/{state['repo']}/actions/runners/{state['runner_id']}"],
            errors,
            "runner",
        )
    if state.get("droplet_id"):
        delete_and_confirm(
            ["doctl", "compute", "droplet", "get", str(state["droplet_id"])],
            ["doctl", "compute", "droplet", "delete", str(state["droplet_id"]), "--force"],
            errors, "droplet", wait_seconds=CREATE_WAIT_SECONDS,
        )
    if state.get("volume_id"):
        delete_and_confirm(
            ["doctl", "compute", "volume", "get", str(state["volume_id"])],
            ["doctl", "compute", "volume", "delete", str(state["volume_id"]), "--force"],
            errors,
            "volume",
        )
    if state.get("firewall_id"):
        delete_and_confirm(
            ["doctl", "compute", "firewall", "get", str(state["firewall_id"])],
            ["doctl", "compute", "firewall", "delete", str(state["firewall_id"]), "--force"],
            errors,
            "firewall",
        )
    if state.get("tag_created") and state.get("tag"):
        delete_and_confirm(
            ["doctl", "compute", "tag", "get", state["tag"]],
            ["doctl", "compute", "tag", "delete", state["tag"], "--force"],
            errors,
            "tag",
        )
    if errors:
        state["phase"] = "destroy-failed"
        state["failure"] = "; ".join(errors)
        save_state(path, state)
        raise LabError("some resources may remain billable: " + "; ".join(errors))
    known_hosts = Path(state["known_hosts_file"]) if state.get("known_hosts_file") else None
    if known_hosts is not None:
        known_hosts.unlink(missing_ok=True)
    path.unlink()
    try:
        path.parent.rmdir()
    except OSError:
        pass
    print("Swan Song Lab runner, Droplet, volume, firewall, and tag are absent.")


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--state", default=str(DEFAULT_STATE), help="local non-secret resource state")
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="operation", required=True)
    launch_parser = sub.add_parser("launch", parents=[common], help="plan or create a prepared one-job lab")
    launch_parser.add_argument("--apply", action="store_true", help="make billable cloud changes")
    launch_parser.add_argument("--accept-quartus-eula", action="store_true")
    launch_parser.add_argument("--name", default="swan-song-quartus-lab")
    launch_parser.add_argument("--repo", default=DEFAULT_REPO)
    launch_parser.add_argument("--region", default=DEFAULT_REGION)
    launch_parser.add_argument("--size", default=DEFAULT_SIZE)
    launch_parser.add_argument("--image", default=DEFAULT_IMAGE)
    launch_parser.add_argument("--volume-gib", type=int, default=DEFAULT_VOLUME_GIB)
    launch_parser.add_argument("--ssh-key", help="existing DigitalOcean SSH key ID or fingerprint")
    launch_parser.add_argument("--identity-file", help="matching local private key; otherwise SSH defaults are used")
    launch_parser.add_argument("--ssh-cidr", help="the Mac's current public IPv4 address with /32")
    launch_parser.add_argument("--quartus-archive", help=f"local {ARCHIVE_NAME}")
    launch_parser.add_argument("--ref", help="local Git ref; defaults to HEAD and must already exist on GitHub")
    launch_parser.set_defaults(handler=launch)
    status_parser = sub.add_parser("status", parents=[common], help="show exact cloud and runner state")
    status_parser.set_defaults(handler=status)
    ssh_parser = sub.add_parser("ssh", parents=[common], help="open SSH or execute a lab command")
    ssh_parser.add_argument("command", nargs=argparse.REMAINDER)
    ssh_parser.set_defaults(handler=ssh_command)
    resume_parser = sub.add_parser("resume", parents=[common], help="continue a stopped lab from a verified image")
    resume_parser.add_argument("--apply", action="store_true")
    resume_parser.set_defaults(handler=resume)
    storage_parser = sub.add_parser(
        "warm-storage", parents=[common], help="move the reusable container image store to the attached volume"
    )
    storage_parser.add_argument("--apply", action="store_true")
    storage_parser.set_defaults(handler=warm_storage)
    rearm_parser = sub.add_parser(
        "rearm", parents=[common], help="reuse the warm lab after its one-job JIT runner is consumed"
    )
    rearm_parser.add_argument("--apply", action="store_true")
    rearm_parser.add_argument("--ref", help="local Git ref; defaults to HEAD and must equal the GitHub default branch")
    rearm_parser.set_defaults(handler=rearm)
    dispatch_parser = sub.add_parser("dispatch", parents=[common], help="plan or dispatch the Quartus workflow")
    dispatch_parser.add_argument("--apply", action="store_true")
    dispatch_parser.add_argument(
        "--profile",
        choices=("candidate", "connectivity-refresh"),
        default="candidate",
    )
    dispatch_parser.add_argument(
        "--ref",
        help="exact GitHub branch; candidate defaults to the repository default branch",
    )
    dispatch_parser.add_argument(
        "--connectivity-refresh-sha",
        help="exact prepared commit required by the connectivity-refresh profile",
    )
    dispatch_parser.set_defaults(handler=dispatch)
    destroy_parser = sub.add_parser("destroy", parents=[common], help="plan or delete every recorded lab resource")
    destroy_parser.add_argument("--apply", action="store_true")
    destroy_parser.add_argument("--confirm")
    destroy_parser.set_defaults(handler=destroy)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        args.handler(args)
    except LabError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
