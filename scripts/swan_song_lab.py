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


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / ".swan-song-lab" / "state.json"
ARCHIVE_NAME = "Quartus-lite-21.1.1.850-linux.tar"
ARCHIVE_SHA1 = "789c1133d99fde7146fdb99c1f5dcb4d2e5cc0cc"
IMAGE = "swan-song-quartus:21.1.1-850-cyclonev"
LABELS = ["self-hosted", "linux", "x64", "swan-song-quartus-21-1-1"]
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
apt-get install -y ca-certificates curl docker.io git jq ufw
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
systemctl stop docker.service docker.socket || true
install -d -m 0755 /srv/swan-song-data /var/lib/docker
mount -o defaults,nofail,discard,noatime {shlex.quote(device)} /srv/swan-song-data
uuid="$(blkid -o value -s UUID {shlex.quote(device)})"
printf 'UUID=%s /srv/swan-song-data ext4 defaults,nofail,discard,noatime 0 2\n' "$uuid" >> /etc/fstab
install -d -m 0711 /srv/swan-song-data/docker
mount --bind /srv/swan-song-data/docker /var/lib/docker
printf '/srv/swan-song-data/docker /var/lib/docker none bind 0 0\n' >> /etc/fstab
systemctl enable --now docker
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
    print(f"  GitHub JIT labels: {', '.join(LABELS)}")
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
        "-o", f"UserKnownHostsFile={state['known_hosts_file']}",
    ]
    if state.get("identity_file"):
        scp.extend(["-i", state["identity_file"]])
    scp.extend([str(archive), f"{ssh_target(state)}:{remote_archive}"])
    run(scp, timeout=COPY_TIMEOUT)
    repo_url = f"https://github.com/{state['repo']}.git"
    remote = f"""set -euo pipefail
archive={shlex.quote(remote_archive)}
cleanup() {{ rm -f "$archive"; }}
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
./scripts/quartus_docker.sh image "$archive"
./scripts/quartus_docker.sh check-image
docker image inspect --format '{{{{.Id}}}}' {shlex.quote(IMAGE)}
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
    mark_pending(state, path, "runner")
    request = {
        "name": state["runner_name"],
        "runner_group_id": 1,
        "labels": LABELS,
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
    if not isinstance(runner, dict) or not isinstance(runner.get("id"), int):
        raise LabError("GitHub JIT response has no runner ID")
    if not isinstance(config, str) or not config or len(config) > 65536:
        raise LabError("GitHub JIT response has no bounded encoded configuration")
    state["runner_id"] = runner["id"]
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
            found_identifier = matches[0].get("id")
            state["runner_id"] = found_identifier
        elif kind == "workflow_run":
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
                and item.get("display_title") == f"Quartus fit candidate {name}"
                and item.get("head_sha") == state["commit"]
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
        if runner is not None and runner.get("status") == "online":
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
        "known_hosts_file": str(path.parent / "known_hosts"),
        "resource_names": {
            "tag": tag,
            "firewall": firewall_name,
            "volume": volume_name,
            "droplet": f"{args.name}-{suffix}",
            "runner": f"{args.name}-{suffix}",
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
                "--outbound-rules",
                "protocol:tcp,ports:all,address:0.0.0.0/0 protocol:udp,ports:all,address:0.0.0.0/0 protocol:icmp,ports:all,address:0.0.0.0/0",
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


def status(args: argparse.Namespace) -> None:
    state = load_state(state_path(args))
    assert state is not None
    require_tools()
    print(f"lab: {state['name']} ({state.get('phase', 'unknown')})")
    print(f"source: {state['repo']}@{state['commit']}")
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


def dispatch(args: argparse.Namespace) -> None:
    path = state_path(args)
    state = load_state(path)
    assert state is not None
    if not args.apply:
        print(f"Would dispatch .github/workflows/quartus-fit.yml on {state['repo']} default branch.")
        print("No workflow was dispatched. Re-run with --apply after status shows the runner online.")
        return
    if state.get("phase") != "ready" or not state.get("runner_id"):
        raise LabError("the prepared JIT runner is not ready")
    if state.get("workflow_run_id") or "workflow_run" in state.get("pending_resources", []):
        raise LabError("this one-job lab already has a recorded or uncertain workflow dispatch")
    require_tools()
    branch = one_object(
        json_command(["gh", "api", f"repos/{state['repo']}/branches/{state['default_branch']}"]),
        "GitHub default branch",
    )
    branch_commit = branch.get("commit", {}).get("sha") if isinstance(branch.get("commit"), dict) else None
    if branch_commit != state["commit"]:
        raise LabError("default-branch head moved after image preparation; destroy and relaunch at the new head")
    nonce = f"swan-lab-{uuid.uuid4().hex}"
    state.setdefault("resource_names", {})["workflow_run"] = nonce
    mark_pending(state, path, "workflow_run")
    response = one_object(
        json_command(
            [
                "gh", "api", "--method", "POST",
                "--header", "X-GitHub-Api-Version: 2026-03-10",
                f"repos/{state['repo']}/actions/workflows/quartus-fit.yml/dispatches",
                "--input", "-",
            ],
            input_body={"ref": state["default_branch"], "inputs": {"lab_nonce": nonce}},
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
        or workflow.get("head_sha") != state["commit"]
        or workflow.get("head_branch") != state["default_branch"]
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
    dispatch_parser = sub.add_parser("dispatch", parents=[common], help="plan or dispatch the Quartus workflow")
    dispatch_parser.add_argument("--apply", action="store_true")
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
