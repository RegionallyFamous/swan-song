#!/usr/bin/env python3
"""Safely commit, push, and open the Swan Song launch-hardening PR.

The default mode is a read-only preflight.  ``--apply`` fetches the base,
requires an explicit confirmation, stages only the paths below, and stops
after opening the pull request.  It never merges and never uses ``git add .``.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


REPOSITORY = "RegionallyFamous/swansong-core"
CANONICAL_REPOSITORY_URL = f"https://github.com/{REPOSITORY}.git"
BASE_BRANCH = "main"
DEFAULT_BRANCH = "codex/launch-hardening"
DEFAULT_TITLE = "Harden Swan Song for hardware qualification and launch"
DEFAULT_COMMIT = "Harden Swan Song launch qualification"

# These are the only changes that belong in the launch-hardening PR.  Status
# codes describe the required pre-staging state: M=modified, D=deleted, A=new.
EXPECTED_CHANGES: dict[str, str] = {
    ".github/workflows/quartus-fit.yml": "M",
    "ARCHITECTURE.md": "M",
    "BUILDING.md": "M",
    "FIRST_CLASS_INPUT_DOCK.md": "M",
    "FRAME_DELIVERY.md": "M",
    "HARDWARE_QA_PROTOCOL.md": "M",
    "HOMEBREW_WONDERWITCH.md": "M",
    "KNOWN_TITLE_COMPATIBILITY.md": "M",
    "LICENSING.md": "M",
    "Makefile": "M",
    "MEMORIES_STAGING.md": "M",
    "PHASE_STATUS.md": "M",
    "POCKET_FIRST_CLASS.md": "M",
    "POCKET_LAUNCHER_LIBRARY.md": "M",
    "POCKET_SD_STAGING.md": "M",
    "PRIVATE_CORPUS_TESTING.md": "M",
    "QUARTUS_FIT_AUDIT.md": "M",
    "QUARTUS_MAC_DOCKER.md": "M",
    "README.md": "M",
    "RELEASE_DECISIONS.md": "A",
    "SAVESTATE_V2_FORMAT.md": "M",
    "SAVESTATE_SDRAM_READER.md": "M",
    "SCREEN_AUTHENTICITY.md": "M",
    "SWAN_SONG_DOCTOR.md": "M",
    "UPSTREAMS.md": "M",
    "dist/Cores/RegionallyFamous.SwanSong/LICENSE-MANIFEST.json": "M",
    "dist/Cores/RegionallyFamous.SwanSong/THIRD-PARTY-NOTICES.txt": "M",
    "dist/Cores/RegionallyFamous.SwanSong/info.txt": "M",
    "dist/Cores/RegionallyFamous.SwanSong/interact.json": "M",
    "docs/wiki/Architecture.md": "M",
    "docs/wiki/Build-and-Test.md": "M",
    "docs/wiki/Controls-and-Settings.md": "M",
    "docs/wiki/Home.md": "M",
    "docs/wiki/Install-Swan-Song.md": "M",
    "docs/wiki/Playing-Games.md": "M",
    "docs/wiki/Troubleshooting-and-Bug-Reports.md": "M",
    "hardware-qa-inventory.example.json": "M",
    "known-title-compatibility.json": "M",
    "scripts/assemble_stable_release.py": "A",
    "scripts/assemble_stable_release_test.py": "A",
    "scripts/build_chip32_pending_diagnostic.py": "A",
    "scripts/build_chip32_pending_diagnostic_test.py": "A",
    "scripts/build_core.sh": "M",
    "scripts/build_core_test.py": "M",
    "scripts/build_release_evidence.py": "A",
    "scripts/build_release_evidence_test.py": "A",
    "scripts/frame_delivery_metrics.py": "M",
    "scripts/frame_delivery_metrics_test.py": "M",
    "scripts/known_title_compatibility.py": "M",
    "scripts/known_title_compatibility_test.py": "M",
    "scripts/license_manifest.py": "M",
    "scripts/license_manifest_test.py": "M",
    "scripts/mapper_2003_gpo_contract_test.py": "A",
    "scripts/memories_channel1_contract_test.py": "M",
    "scripts/package_core.py": "M",
    "scripts/package_core_test.py": "M",
    "scripts/pocket_console_setup_contract_test.py": "M",
    "scripts/pocket_control_layout_contract_test.py": "M",
    "scripts/pocket_hardware_qa.py": "M",
    "scripts/pocket_hardware_qa_test.py": "M",
    "scripts/pocket_hardware_qa_session.py": "A",
    "scripts/pocket_hardware_qa_session_test.py": "A",
    "scripts/pocket_first_class_contract_test.py": "M",
    "scripts/pocket_menu_focus_contract_test.py": "M",
    "scripts/pocket_per_game_preset.py": "M",
    "scripts/pocket_per_game_preset_test.py": "M",
    "scripts/pocket_savestate_contract_test.py": "M",
    "scripts/pocket_synchronizer_attribute_contract_test.py": "M",
    "scripts/pocket_video_contract_test.py": "M",
    "scripts/prepare_hardware_qa_workspace.py": "A",
    "scripts/prepare_hardware_qa_workspace_test.py": "A",
    "scripts/prepare_launch_pr.py": "A",
    "scripts/prepare_launch_pr_test.py": "A",
    "scripts/prepare_known_title_qa_workspace.py": "A",
    "scripts/prepare_known_title_qa_workspace_test.py": "A",
    "scripts/quartus_fit_audit.py": "M",
    "scripts/quartus_fit_audit_test.py": "M",
    "scripts/quartus_connectivity_policy_refresh_test.py": "M",
    "scripts/quartus_docker.sh": "M",
    "scripts/quartus_docker_contract_test.py": "M",
    "scripts/quartus_evidence.py": "M",
    "scripts/regression.sh": "M",
    "scripts/stage_pocket_sd.py": "M",
    "scripts/stage_pocket_sd_test.py": "M",
    "scripts/swan_song_doctor.py": "M",
    "scripts/swan_song_doctor_test.py": "M",
    "scripts/wiki_sync.py": "A",
    "scripts/wiki_sync_test.py": "A",
    "scripts/with_native_macos_ghdl.sh": "A",
    "scripts/with_native_macos_ghdl_test.py": "A",
    "sim/rtl/apf_console_setup_tb.sv": "D",
    "sim/rtl/apf_interact_readback_tb.sv": "A",
    "sim/rtl/apf_menu_focus_cdc_tb.sv": "A",
    "sim/rtl/apf_menu_focus_pause_tb.sv": "A",
    "sim/rtl/apf_scanout_cadence_tb.sv": "M",
    "sim/rtl/apf_savestate_sdram_reader_tb.sv": "M",
    "sim/rtl/apf_savestate_v2_load_settle_guard_tb.sv": "A",
    "sim/rtl/apf_savestate_v2_owner_tb.sv": "M",
    "sim/rtl/apf_savestate_v2_restore_preflight_tb.sv": "A",
    "sim/rtl/apf_settings_boot_barrier_tb.sv": "M",
    "sim/rtl/apf_system_type_reset_composition_tb.sv": "M",
    "sim/rtl/apf_temporal_blend_tb.sv": "M",
    "sim/rtl/eeprom_state_tb.vhd": "M",
    "sim/rtl/footer_snapshot_tb.sv": "M",
    "sim/rtl/mapper_2003_alias_tb.vhd": "M",
    "sim/rtl/mapper_2003_flash_ce_tb.vhd": "M",
    "sim/rtl/rtc_state_tb.vhd": "M",
    "sim/rtl/run_sdram_quiescent_tb.sh": "M",
    "sim/rtl/run_apf_menu_focus_cdc_tb.sh": "A",
    "sim/rtl/run_apf_interact_readback_tb.sh": "A",
    "sim/rtl/run_apf_menu_focus_pause_tb.sh": "A",
    "sim/rtl/run_apf_scanout_cadence_tb.sh": "M",
    "sim/rtl/run_apf_savestate_v2_load_settle_guard_tb.sh": "A",
    "sim/rtl/run_apf_savestate_v2_restore_preflight_tb.sh": "A",
    "sim/rtl/run_swantop_menu_pause_tb.sh": "A",
    "sim/rtl/swantop_menu_pause_tb.sv": "A",
    "sim/rtl/sdram_quiescent_tb.sv": "M",
    "sim/verilator/TRACE.md": "M",
    "sim/verilator/generate_bank_probe.py": "M",
    "sim/verilator/generate_provenance_probe.py": "M",
    "sim/verilator/generate_provenance_probe_test.py": "M",
    "sim/verilator/generate_rep_movsb_probe.py": "A",
    "sim/verilator/generate_sram_persistence_probes.py": "A",
    "sim/verilator/generate_sram_persistence_probes_test.py": "A",
    "sim/verilator/run_sram_persistence_e2e.sh": "A",
    "sim/verilator/generate_window_boundary_probe.py": "A",
    "sim/verilator/generate_window_boundary_probe_test.py": "A",
    "sim/verilator/sim_main.cpp": "M",
    "sim/verilator/verify_sram_persistence_save.py": "A",
    "sim/verilator/verify_sram_persistence_save_test.py": "A",
    "sim/verilator/verify_bank_probe_test.py": "M",
    "sim/verilator/verify_cpu_rep_movsb.py": "D",
    "sim/verilator/verify_cpu_rep_movsb_test.py": "D",
    "sim/verilator/verify_rep_movsb_probe.py": "A",
    "sim/verilator/verify_rep_movsb_probe_test.py": "A",
    "sim/verilator/verify_window_boundary_probe.py": "A",
    "sim/verilator/verify_window_boundary_probe_test.py": "A",
    "src/fpga/ap_core.qsf": "M",
    "src/fpga/core/apf_console_setup.sv": "D",
    "src/fpga/core/apf_interact_readback.sv": "A",
    "src/fpga/core/apf_menu_focus_cdc.sv": "A",
    "src/fpga/core/apf_scanout_cadence.sv": "M",
    "src/fpga/core/apf_savestate_sdram_reader.sv": "M",
    "src/fpga/core/apf_savestate_v2_layout_pkg.sv": "M",
    "src/fpga/core/apf_savestate_v2_load_settle_guard.sv": "A",
    "src/fpga/core/apf_savestate_v2_owner.sv": "M",
    "src/fpga/core/apf_savestate_v2_restore_preflight.sv": "A",
    "src/fpga/core/apf_temporal_blend.sv": "M",
    "src/fpga/core/core_top.v": "M",
    "src/fpga/core/rtl/IRQ.vhd": "M",
    "src/fpga/core/rtl/cpu.vhd": "M",
    "src/fpga/core/rtl/dma.vhd": "M",
    "src/fpga/core/rtl/dummyregs.vhd": "M",
    "src/fpga/core/rtl/eeprom.vhd": "M",
    "src/fpga/core/rtl/gpu.vhd": "M",
    "src/fpga/core/rtl/gpu_bg.vhd": "M",
    "src/fpga/core/rtl/joypad.vhd": "M",
    "src/fpga/core/rtl/memorymux.vhd": "M",
    "src/fpga/core/rtl/reg_savestates.vhd": "M",
    "src/fpga/core/rtl/reg_swan.vhd": "M",
    "src/fpga/core/rtl/registerpackage.vhd": "M",
    "src/fpga/core/rtl/rtc.vhd": "M",
    "src/fpga/core/rtl/savestate_ui.sv": "M",
    "src/fpga/core/rtl/savestates.vhd": "M",
    "src/fpga/core/rtl/sdram.sv": "M",
    "src/fpga/core/rtl/sprites.vhd": "M",
    "src/fpga/core/rtl/swanTop.vhd": "M",
    "src/fpga/core/wonderswan.sv": "M",
    "testroms/spritepriority/WonderSwan.inc": "D",
    "testroms/spritepriority/ascii.gfx": "D",
    "testroms/spritepriority/build.bat": "D",
    "testroms/spritepriority/spritepriority.asm": "D",
    "testroms/spritepriority/spritepriority.ws": "D",
    "testroms/timingtest/WonderSwan.inc": "D",
    "testroms/timingtest/ascii.gfx": "D",
    "testroms/timingtest/build.bat": "D",
    "testroms/timingtest/testcalls.asm": "D",
    "testroms/timingtest/tests_op.asm": "D",
    "testroms/timingtest/tests_special.asm": "D",
    "testroms/timingtest/texts.asm": "D",
    "testroms/timingtest/timingtest.asm": "D",
    "testroms/timingtest/timingtest.ws": "D",
    "testroms/windowtest/WonderSwan.inc": "D",
    "testroms/windowtest/ascii.gfx": "D",
    "testroms/windowtest/build.bat": "D",
    "testroms/windowtest/windowtest.asm": "D",
    "testroms/windowtest/windowtest.ws": "D",
    "toolchains/quartus-21.1.1/container-build-core.sh": "M",
}

# Existing user work that belongs to other projects or local tooling.  These
# paths must remain present and untracked, are never passed to git-add, and are
# rechecked after the launch-hardening commit before anything is pushed.
PRESERVED_UNTRACKED = frozenset(
    {
        ".DS_Store",
        "build_macrofab_workbook.mjs",
        "hardware/",
        "macos/",
        "node_modules",
        "outputs/",
        "previews/",
        "swantroller-review/",
        "swantroller-rp2040-jlcpcb/",
        "swantroller-rp2040-macrofab/",
        "tmp/",
        "wordpress-rom-patcher/",
    }
)


class HandoffError(RuntimeError):
    """A safe, actionable handoff failure."""


def command(
    args: list[str], cwd: Path, *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostics"
        raise HandoffError(f"command failed ({' '.join(args)}): {detail}")
    return result


def git(cwd: Path, *args: str) -> str:
    return command(["git", *args], cwd).stdout.strip()


def require_tools() -> None:
    missing = [name for name in ("git", "gh") if shutil.which(name) is None]
    if missing:
        raise HandoffError(f"required command not found: {', '.join(missing)}")


def repository_root(cwd: Path) -> Path:
    value = git(cwd, "rev-parse", "--show-toplevel")
    return Path(value).resolve()


def verify_repository_identity(root: Path) -> None:
    remote = git(root, "config", "--get", "remote.origin.url")
    accepted = {
        f"https://github.com/{REPOSITORY}.git".lower(),
        f"https://github.com/{REPOSITORY}".lower(),
        f"git@github.com:{REPOSITORY}.git".lower(),
        f"git@github.com:{REPOSITORY}".lower(),
        f"ssh://git@github.com/{REPOSITORY}.git".lower(),
        f"ssh://git@github.com/{REPOSITORY}".lower(),
    }
    if remote.lower() not in accepted:
        raise HandoffError(
            f"origin is {remote!r}; expected the GitHub repository {REPOSITORY!r}"
        )

    command(["gh", "auth", "status", "--hostname", "github.com"], root)
    owner = command(
        [
            "gh",
            "repo",
            "view",
            REPOSITORY,
            "--json",
            "nameWithOwner",
            "--jq",
            ".nameWithOwner",
        ],
        root,
    ).stdout.strip()
    if owner.lower() != REPOSITORY.lower():
        raise HandoffError(
            f"gh resolved {owner!r}; expected repository {REPOSITORY!r}"
        )


def verify_no_url_rewrites(root: Path) -> None:
    """Reject effective Git URL rewrites that can redirect our network URLs.

    A literal push URL is still subject to Git's ``url.*.insteadOf`` and
    ``url.*.pushInsteadOf`` configuration.  Query the effective, include-aware
    configuration in repository context so local, global, conditional include,
    and command/environment-provided entries are all visible.  This check is
    deliberately repeated around the apply flow; a matching rewrite is never
    a supported way to test or publish Swan Song.
    """

    origin_url = git(root, "config", "--get", "remote.origin.url")
    protected_urls = (CANONICAL_REPOSITORY_URL, origin_url)
    result = subprocess.run(
        [
            "git",
            "config",
            "--includes",
            "--null",
            "--show-origin",
            "--show-scope",
            "--get-regexp",
            r"^url\..*\.(insteadof|pushinsteadof)$",
        ],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    # git-config returns 1 when no matching key exists.
    if result.returncode == 1:
        return
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "no diagnostics"
        raise HandoffError(f"could not audit Git URL rewrites: {detail}")

    fields = result.stdout.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    if len(fields) % 3:
        raise HandoffError("could not parse effective Git URL rewrite configuration")
    for index in range(0, len(fields), 3):
        scope = fields[index].decode(errors="replace")
        origin = fields[index + 1].decode(errors="replace")
        pair = fields[index + 2].decode(errors="replace")
        key, separator, match_prefix = pair.partition("\n")
        if not separator:
            raise HandoffError(
                "could not parse effective Git URL rewrite key/value pair"
            )
        if any(url.startswith(match_prefix) for url in protected_urls):
            raise HandoffError(
                f"Git URL rewrite {key!r} from {scope} scope at {origin!r} "
                f"matches a protected repository URL; remove it before handoff"
            )


def parse_status(root: Path) -> dict[str, str]:
    raw = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=normal",
        ],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if raw.returncode:
        raise HandoffError(raw.stderr.decode(errors="replace").strip())

    changes: dict[str, str] = {}
    for record in raw.stdout.split(b"\0"):
        if not record:
            continue
        if len(record) < 4 or record[2:3] != b" ":
            raise HandoffError("could not parse git status safely")
        xy = record[:2].decode("ascii", errors="replace")
        path = record[3:].decode(errors="surrogateescape")
        if "R" in xy or "C" in xy:
            raise HandoffError(f"renames/copies are not allowed in handoff: {path}")
        if path in changes:
            raise HandoffError(f"duplicate status path: {path}")
        if xy == "??":
            code = "A"
        elif xy == " M":
            code = "M"
        elif xy == " D":
            code = "D"
        else:
            raise HandoffError(
                f"{path}: unsupported status {xy!r}; the index must be untouched"
            )
        changes[path] = code
    return changes


def verify_expected_changes(root: Path) -> None:
    actual = parse_status(root)
    intended = set(EXPECTED_CHANGES)
    preserved = set(PRESERVED_UNTRACKED)
    missing = sorted((intended | preserved) - set(actual))
    extra = sorted(set(actual) - intended - preserved)
    wrong = sorted(
        path
        for path in set(actual) & (intended | preserved)
        if actual[path] != (EXPECTED_CHANGES[path] if path in intended else "A")
    )
    if not (missing or extra or wrong):
        return

    lines = ["working tree does not match the launch-hardening allowlist:"]
    lines.extend(
        f"  missing {EXPECTED_CHANGES[path] if path in intended else 'A'}  {path}"
        for path in missing
    )
    lines.extend(f"  unexpected {actual[path]}  {path}" for path in extra)
    lines.extend(
        f"  wrong status {actual[path]} "
        f"(expected {EXPECTED_CHANGES[path] if path in intended else 'A'})  {path}"
        for path in wrong
    )
    lines.append("No files were staged or changed by this command.")
    raise HandoffError("\n".join(lines))


def verify_branch_name(root: Path, branch: str) -> None:
    if not branch.startswith("codex/"):
        raise HandoffError("handoff branch must use the codex/ prefix")
    command(["git", "check-ref-format", "--branch", branch], root)
    exists = command(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        root,
        check=False,
    )
    if exists.returncode == 0:
        raise HandoffError(f"local branch already exists: {branch}")
    if exists.returncode not in (0, 1):
        raise HandoffError(f"could not inspect local branch: {branch}")


def resolve_commit(root: Path, ref: str) -> str:
    return git(root, "rev-parse", "--verify", f"{ref}^{{commit}}")


def tree_id(root: Path, ref: str) -> str:
    return git(root, "rev-parse", "--verify", f"{ref}^{{tree}}")


def inspect_remote(root: Path) -> tuple[str, str]:
    output = git(root, "ls-remote", "--exit-code", "origin", f"refs/heads/{BASE_BRANCH}")
    fields = output.split()
    if len(fields) != 2 or fields[1] != f"refs/heads/{BASE_BRANCH}":
        raise HandoffError(f"unexpected origin/{BASE_BRANCH} response")
    remote_commit = fields[0]
    tracking_commit = resolve_commit(root, f"refs/remotes/origin/{BASE_BRANCH}")
    return remote_commit, tracking_commit


def verify_remote_branch_absent(root: Path, branch: str) -> None:
    result = command(
        ["git", "ls-remote", "--exit-code", "origin", f"refs/heads/{branch}"],
        root,
        check=False,
    )
    if result.returncode == 0:
        raise HandoffError(f"remote branch already exists: origin/{branch}")
    # git-ls-remote documents status 2 for --exit-code with no matching ref.
    if result.returncode != 2:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostics"
        raise HandoffError(f"could not inspect origin/{branch}: {detail}")


def verify_base_tree(root: Path) -> tuple[str, str]:
    head_tree = tree_id(root, "HEAD")
    base_ref = f"refs/remotes/origin/{BASE_BRANCH}"
    base_tree = tree_id(root, base_ref)
    if head_tree != base_tree:
        raise HandoffError(
            "local HEAD tree does not equal the freshly fetched origin/main tree; "
            "move these changes onto the current main base before handoff"
        )
    return resolve_commit(root, "HEAD"), resolve_commit(root, base_ref)


def parse_name_status(raw: str) -> dict[str, str]:
    fields = raw.split("\0") if raw else []
    if fields and fields[-1] == "":
        fields.pop()
    if len(fields) % 2:
        raise HandoffError("could not parse name/status change set safely")
    return {fields[index + 1]: fields[index] for index in range(0, len(fields), 2)}


def verify_staged_changes(root: Path) -> None:
    actual = parse_name_status(git(root, "diff", "--cached", "--name-status", "-z"))
    if actual != EXPECTED_CHANGES:
        raise HandoffError("staged change set differs from the exact handoff allowlist")
    command(["git", "diff", "--cached", "--check"], root)


def verify_preserved_untracked(root: Path) -> None:
    expected = {path: "A" for path in PRESERVED_UNTRACKED}
    actual = parse_status(root)
    if actual != expected:
        raise HandoffError(
            "commit completed but the working tree is not exactly the preserved "
            "untracked set; not pushing"
        )


def print_preservation_warning() -> None:
    print("WARNING: preserving these explicit untracked paths; none will be staged:")
    for path in sorted(PRESERVED_UNTRACKED):
        print(f"  {path}")


def confirmation(branch: str) -> str:
    return f"PUSH {branch} AND OPEN PR"


def pull_request_body(base_commit: str) -> str:
    return f"""## Summary

- harden deterministic release evidence, packaging, and SD staging
- replace inherited probe assets with project-authored qualification probes
- add the complete Pocket/Dock hardware qualification handoff
- preserve fail-closed licensing and launch gates

## Base

`origin/{BASE_BRANCH}` at `{base_commit}`

## Launch policy

This pull request does not merge or publish a release. Physical Pocket/Dock QA,
fresh Quartus evidence, reproducibility, and distribution authorization remain
required before a stable release.
"""


def dry_run(root: Path, branch: str) -> None:
    remote_commit, tracking_commit = inspect_remote(root)
    head_tree = tree_id(root, "HEAD")
    tracking_tree = tree_id(root, f"refs/remotes/origin/{BASE_BRANCH}")
    print("Swan Song launch-hardening handoff: DRY RUN")
    print(f"repository: {REPOSITORY}")
    print(f"changes: {len(EXPECTED_CHANGES)} exact allowlisted paths")
    print(f"remote main: {remote_commit}")
    print(f"local origin/main: {tracking_commit}")
    if remote_commit != tracking_commit:
        print("note: --apply will fetch origin/main before making any branch change")
    if head_tree != tracking_tree:
        raise HandoffError(
            "local HEAD tree does not equal the current local origin/main tree"
        )
    print(f"planned branch: {branch}")
    print("planned endpoint: pushed branch plus open pull request; no merge")
    print(f"To apply, run: python3 scripts/prepare_launch_pr.py --apply --branch {branch}")


def apply(root: Path, branch: str, title: str, commit_message: str) -> None:
    verify_no_url_rewrites(root)
    git(
        root,
        "fetch",
        "--no-tags",
        "origin",
        f"+refs/heads/{BASE_BRANCH}:refs/remotes/origin/{BASE_BRANCH}",
    )
    head_commit, base_commit = verify_base_tree(root)
    phrase = confirmation(branch)
    print(
        f"Verified HEAD at {head_commit} has the same tree as fetched "
        f"origin/main at {base_commit}."
    )
    print(f"Type exactly: {phrase}")
    if input("> ").strip() != phrase:
        raise HandoffError("confirmation did not match; no branch was created")

    git(root, "switch", "--create", branch, f"refs/remotes/origin/{BASE_BRANCH}")
    paths = sorted(EXPECTED_CHANGES)
    command(["git", "add", "--", *paths], root)
    verify_staged_changes(root)
    git(root, "commit", "-m", commit_message)
    committed = parse_name_status(
        git(
            root,
            "diff",
            "--name-status",
            "-z",
            f"refs/remotes/origin/{BASE_BRANCH}..HEAD",
        )
    )
    if committed != EXPECTED_CHANGES:
        raise HandoffError(
            "commit differs from the exact handoff allowlist; not pushing"
        )
    verify_preserved_untracked(root)
    verify_no_url_rewrites(root)
    # Push exactly one new branch to the verified canonical repository.  Do
    # not consult remote.origin.pushurl, do not inherit push.followTags, and
    # require the destination ref to remain absent after the earlier preflight
    # check.  The empty lease makes a concurrent branch creation fail instead
    # of allowing a normal fast-forward overwrite.
    git(
        root,
        "push",
        "--no-follow-tags",
        f"--force-with-lease=refs/heads/{branch}:",
        CANONICAL_REPOSITORY_URL,
        f"HEAD:refs/heads/{branch}",
    )

    result = command(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            REPOSITORY,
            "--base",
            BASE_BRANCH,
            "--head",
            branch,
            "--title",
            title,
            "--body",
            pull_request_body(base_commit),
        ],
        root,
    )
    print("Pull request opened; this command intentionally did not merge it.")
    print(result.stdout.strip())


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="create, push, and open the PR")
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--commit-message", default=DEFAULT_COMMIT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        require_tools()
        root = repository_root(Path.cwd())
        verify_branch_name(root, args.branch)
        verify_no_url_rewrites(root)
        verify_repository_identity(root)
        verify_remote_branch_absent(root, args.branch)
        verify_expected_changes(root)
        command(["git", "diff", "--check"], root)
        print_preservation_warning()
        if args.apply:
            apply(root, args.branch, args.title, args.commit_message)
        else:
            dry_run(root, args.branch)
    except (HandoffError, EOFError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
