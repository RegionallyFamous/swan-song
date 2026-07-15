#!/usr/bin/env python3
"""Safely synchronize the reviewed Swan Song Wiki source into a local clone.

``docs/wiki`` remains the reviewable source of truth.  The default mode is a
strictly read-only plan.  Publication requires both ``--apply`` and an exact,
noninteractive repository confirmation.  This tool never clones or fetches;
the operator must explicitly supply a clean local clone of the GitHub Wiki.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Sequence

import wiki_publication_check as publication


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "RegionallyFamous/swansong-core.wiki"
CONFIRMATION = REPOSITORY
DEFAULT_COMMIT_MESSAGE = "Sync reviewed Swan Song Wiki pages"
SAFE_PAGE_NAME = re.compile(r"(?:[A-Za-z0-9][A-Za-z0-9_-]*|_[A-Za-z0-9_-]+)\.md\Z")


class WikiSyncError(RuntimeError):
    """A synchronization precondition or operation failed closed."""


@dataclass(frozen=True)
class PlanEntry:
    operation: str
    path: str
    source_sha256: str | None
    clone_sha256: str | None


@dataclass(frozen=True)
class SyncPlan:
    source_root: Path
    wiki_clone: Path
    repository: str
    branch: str
    head: str
    entries: tuple[PlanEntry, ...]

    def document(self) -> dict[str, object]:
        counts = {
            operation: sum(item.operation == operation for item in self.entries)
            for operation in ("add", "change", "delete")
        }
        return {
            "status": "ready",
            "mode": "dry-run",
            "network_access": False,
            "publication_performed": False,
            "repository": self.repository,
            "source_root": str(self.source_root),
            "wiki_clone": str(self.wiki_clone),
            "branch": self.branch,
            "head": self.head,
            "counts": counts,
            "plan": [asdict(item) for item in self.entries],
        }


@dataclass(frozen=True)
class ApplyResult:
    plan: SyncPlan
    committed: bool
    pushed: bool
    commit: str | None

    def document(self) -> dict[str, object]:
        result = self.plan.document()
        result.update(
            {
                "status": "published" if self.pushed else "no_changes",
                "mode": "apply",
                "network_access": self.committed,
                "publication_performed": self.pushed,
                "committed": self.committed,
                "pushed": self.pushed,
                "commit": self.commit,
            }
        )
        return result


def _safe_directory(path: Path, label: str) -> Path:
    try:
        metadata = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise WikiSyncError(f"cannot inspect {label}: {error}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise WikiSyncError(f"{label} must be an existing nonsymlink directory: {path}")
    try:
        return path.resolve(strict=True)
    except OSError as error:
        raise WikiSyncError(f"cannot resolve {label}: {error}") from error


def _git_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "Never",
            "GH_PROMPT_DISABLED": "1",
            "GIT_EDITOR": ":",
            "GIT_SEQUENCE_EDITOR": ":",
            "LC_ALL": "C",
        }
    )
    environment.setdefault("GIT_SSH_COMMAND", "ssh -oBatchMode=yes")
    return environment


def _run_git(
    clone: Path,
    arguments: Sequence[str],
    *,
    check: bool = True,
    timeout: int = 15,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            [
                "git",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
                "-C",
                str(clone),
                *arguments,
            ],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            env=_git_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise WikiSyncError(f"git {' '.join(arguments)} could not run: {error}") from error
    if check and result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise WikiSyncError(
            f"git {' '.join(arguments)} failed"
            + (f": {detail}" if detail else f" with exit {result.returncode}")
        )
    return result


def _decode(value: bytes, label: str) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeError as error:
        raise WikiSyncError(f"{label} is not valid UTF-8") from error


def _config_values(clone: Path, key: str) -> tuple[str, ...]:
    result = _run_git(clone, ("config", "--null", "--get-all", key), check=False)
    if result.returncode == 1:
        return ()
    if result.returncode != 0:
        detail = _decode(result.stderr, "git config error").strip()
        raise WikiSyncError(f"cannot read Git configuration {key}: {detail}")
    return tuple(
        _decode(value, f"Git configuration {key}")
        for value in result.stdout.split(b"\0")
        if value
    )


def _expected_remote(url: str) -> bool:
    patterns = (
        r"https://github\.com/RegionallyFamous/swansong-core\.wiki(?:\.git)?/?",
        r"git@github\.com:RegionallyFamous/swansong-core\.wiki(?:\.git)?",
        r"ssh://git@github\.com/RegionallyFamous/swansong-core\.wiki(?:\.git)?/?",
    )
    return any(re.fullmatch(pattern, url, re.IGNORECASE) for pattern in patterns)


def _safe_page_name(name: str) -> bool:
    return (
        bool(SAFE_PAGE_NAME.fullmatch(name))
        and name not in {".", ".."}
        and not name.startswith(".git")
    )


def _clone_pages(clone: Path) -> tuple[str, ...]:
    pages: list[str] = []
    try:
        entries = tuple(os.scandir(clone))
    except OSError as error:
        raise WikiSyncError(f"cannot enumerate wiki clone: {error}") from error
    for entry in entries:
        if entry.name == ".git":
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise WikiSyncError(f"cannot inspect wiki clone .git: {error}") from error
            if entry.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
                raise WikiSyncError("wiki clone .git must be a real directory")
            continue
        if not _safe_page_name(entry.name):
            raise WikiSyncError(
                f"unexpected wiki-clone entry (only root-level Markdown pages are safe): {entry.name!r}"
            )
        try:
            metadata = entry.stat(follow_symlinks=False)
        except OSError as error:
            raise WikiSyncError(f"cannot inspect wiki page {entry.name}: {error}") from error
        if entry.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise WikiSyncError(
                f"wiki clone page must be a regular nonsymlink file: {entry.name}"
            )
        if metadata.st_size > publication.MAX_MARKDOWN_BYTES:
            raise WikiSyncError(
                f"wiki clone page exceeds the {publication.MAX_MARKDOWN_BYTES}-byte limit: {entry.name}"
            )
        pages.append(entry.name)
    if ".git" not in {entry.name for entry in entries}:
        raise WikiSyncError("wiki clone does not contain a .git directory")
    folded: dict[str, str] = {}
    for name in pages:
        key = name.casefold()
        if key in folded and folded[key] != name:
            raise WikiSyncError(f"case-colliding wiki pages are unsafe: {folded[key]}, {name}")
        folded[key] = name
    return tuple(sorted(pages))


def _git_text(clone: Path, arguments: Sequence[str], label: str) -> str:
    return _decode(_run_git(clone, arguments).stdout, label).strip()


def _inspect_clone(clone: Path) -> tuple[str, str, tuple[str, ...]]:
    git_directory = clone / ".git"
    try:
        metadata = os.stat(git_directory, follow_symlinks=False)
    except OSError as error:
        raise WikiSyncError(f"wiki clone has no inspectable .git directory: {error}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise WikiSyncError("wiki clone .git must be a real directory, not a link or worktree file")

    top = _git_text(clone, ("rev-parse", "--show-toplevel"), "Git worktree root")
    try:
        top_path = Path(top).resolve(strict=True)
    except OSError as error:
        raise WikiSyncError(f"cannot resolve Git worktree root: {error}") from error
    if top_path != clone:
        raise WikiSyncError(f"supplied wiki clone is not its Git worktree root: {clone}")

    status = _run_git(
        clone,
        ("status", "--porcelain=v1", "-z", "--untracked-files=all"),
    ).stdout
    if status:
        count = len([value for value in status.split(b"\0") if value])
        raise WikiSyncError(f"wiki clone must be clean ({count} status entries found)")

    fetch_urls = _config_values(clone, "remote.origin.url")
    push_urls = _config_values(clone, "remote.origin.pushurl") or fetch_urls
    if len(fetch_urls) != 1 or len(push_urls) != 1:
        raise WikiSyncError("wiki clone must have exactly one origin fetch URL and one effective push URL")
    if not _expected_remote(fetch_urls[0]) or not _expected_remote(push_urls[0]):
        raise WikiSyncError(
            f"origin must fetch and push only {REPOSITORY}; found {fetch_urls[0]!r} / {push_urls[0]!r}"
        )
    effective_fetch = tuple(
        _decode(value, "effective origin fetch URL")
        for value in _run_git(clone, ("remote", "get-url", "--all", "origin")).stdout.splitlines()
        if value
    )
    effective_push = tuple(
        _decode(value, "effective origin push URL")
        for value in _run_git(
            clone, ("remote", "get-url", "--push", "--all", "origin")
        ).stdout.splitlines()
        if value
    )
    if (
        len(effective_fetch) != 1
        or len(effective_push) != 1
        or not _expected_remote(effective_fetch[0])
        or not _expected_remote(effective_push[0])
    ):
        raise WikiSyncError(
            "Git URL rewriting must not redirect the expected origin fetch or push URL"
        )

    branch = _git_text(clone, ("symbolic-ref", "--quiet", "--short", "HEAD"), "Git branch")
    if not branch or branch.startswith("-"):
        raise WikiSyncError("wiki clone must be on a named branch")
    ref_check = _run_git(clone, ("check-ref-format", "--branch", branch), check=False)
    if ref_check.returncode != 0:
        raise WikiSyncError(f"wiki clone branch name is unsafe: {branch!r}")
    upstream = _git_text(
        clone,
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"),
        "Git upstream",
    )
    if upstream != f"origin/{branch}":
        raise WikiSyncError(
            f"wiki clone branch must track origin/{branch}; found {upstream!r}"
        )
    divergence = _git_text(
        clone,
        ("rev-list", "--left-right", "--count", "HEAD...@{upstream}"),
        "Git divergence",
    ).split()
    if divergence != ["0", "0"]:
        raise WikiSyncError(
            "wiki clone must have no locally known ahead/behind commits; fetch separately, then retry"
        )
    head = _git_text(clone, ("rev-parse", "--verify", "HEAD^{commit}"), "Git HEAD")

    pages = _clone_pages(clone)
    tracked_raw = _run_git(clone, ("ls-files", "-z", "--cached")).stdout
    tracked = tuple(
        sorted(
            _decode(value, "tracked wiki path")
            for value in tracked_raw.split(b"\0")
            if value
        )
    )
    if tracked != pages:
        raise WikiSyncError(
            "wiki clone tracked paths must exactly equal its safe root-level Markdown pages"
        )
    return branch, head, pages


def _read_page(path: Path, label: str) -> bytes:
    try:
        metadata = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise WikiSyncError(f"cannot inspect {label}: {error}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise WikiSyncError(f"{label} must be a regular nonsymlink file")
    if metadata.st_size > publication.MAX_MARKDOWN_BYTES:
        raise WikiSyncError(f"{label} exceeds the publication size limit")
    try:
        value = path.read_bytes()
        value.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise WikiSyncError(f"cannot read UTF-8 {label}: {error}") from error
    return value


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def build_plan(source_root: Path, wiki_clone: Path) -> SyncPlan:
    source = _safe_directory(source_root, "source root")
    clone = _safe_directory(wiki_clone, "wiki clone")
    if source == clone or source in clone.parents or clone in source.parents:
        raise WikiSyncError("source root and wiki clone must be separate directory trees")

    try:
        audit = publication.check_publication(source)
    except publication.PublicationCheckError as error:
        raise WikiSyncError(f"wiki publication audit could not run: {error}") from error
    if not audit.ok:
        details = "; ".join(
            f"{finding.code} at {finding.location}: {finding.message}"
            for finding in audit.findings
            if finding.severity == "ERROR"
        )
        raise WikiSyncError(f"wiki_publication_check rejected docs/wiki: {details}")

    branch, head, clone_pages = _inspect_clone(clone)
    source_pages = tuple(publication.WIKI_MANIFEST)
    entries: list[PlanEntry] = []
    for name in sorted(set(source_pages) | set(clone_pages)):
        source_value = (
            _read_page(source / publication.WIKI_RELATIVE / name, f"source page {name}")
            if name in source_pages
            else None
        )
        clone_value = (
            _read_page(clone / name, f"wiki clone page {name}")
            if name in clone_pages
            else None
        )
        if source_value is None:
            operation = "delete"
        elif clone_value is None:
            operation = "add"
        elif source_value != clone_value:
            operation = "change"
        else:
            continue
        entries.append(
            PlanEntry(
                operation=operation,
                path=name,
                source_sha256=_digest(source_value) if source_value is not None else None,
                clone_sha256=_digest(clone_value) if clone_value is not None else None,
            )
        )
    entries.sort(key=lambda item: ({"add": 0, "change": 1, "delete": 2}[item.operation], item.path))
    return SyncPlan(source, clone, REPOSITORY, branch, head, tuple(entries))


def render_plan(plan: SyncPlan) -> str:
    lines = [
        "SWAN SONG WIKI SYNC PLAN: READY",
        "Mode: dry-run; no files, commits, remotes, or network state changed",
        f"Repository: {plan.repository}",
        f"Wiki clone: {plan.wiki_clone}",
        f"Branch / HEAD: {plan.branch} / {plan.head}",
    ]
    for operation in ("add", "change", "delete"):
        selected = [item for item in plan.entries if item.operation == operation]
        lines.append("")
        lines.append(f"{operation.upper()} ({len(selected)})")
        lines.extend(f"  {item.path}" for item in selected)
        if not selected:
            lines.append("  none")
    lines.extend(
        (
            "",
            "No publication was performed.",
            f"To apply exactly this workflow, re-run with --apply --confirm-publish {CONFIRMATION}",
        )
    )
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, value: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=".swan-song-wiki-sync-"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _rollback(clone: Path, originals: dict[str, bytes | None]) -> None:
    names = tuple(sorted(originals))
    _run_git(clone, ("reset", "--quiet", "HEAD", "--", *names), check=False)
    for name, value in originals.items():
        path = clone / name
        if value is None:
            if path.exists() or path.is_symlink():
                path.unlink()
        else:
            _atomic_write(path, value)


def _cached_plan(clone: Path) -> dict[str, str]:
    raw = _run_git(
        clone, ("diff", "--cached", "--name-status", "--no-renames", "-z")
    ).stdout
    values = [value for value in raw.split(b"\0") if value]
    if len(values) % 2:
        raise WikiSyncError("cannot parse staged Wiki change list")
    status_to_operation = {b"A": "add", b"M": "change", b"D": "delete"}
    result: dict[str, str] = {}
    for index in range(0, len(values), 2):
        status, raw_name = values[index : index + 2]
        if status not in status_to_operation:
            raise WikiSyncError(f"unexpected staged Git status: {status!r}")
        name = _decode(raw_name, "staged Wiki path")
        if not _safe_page_name(name):
            raise WikiSyncError(f"unsafe staged Wiki path: {name!r}")
        result[name] = status_to_operation[status]
    return result


def apply_plan(plan: SyncPlan, confirmation: str, commit_message: str) -> ApplyResult:
    if confirmation != CONFIRMATION:
        raise WikiSyncError(
            f"publication confirmation must exactly equal {CONFIRMATION!r}"
        )
    if not commit_message.strip() or "\x00" in commit_message or "\n" in commit_message or "\r" in commit_message:
        raise WikiSyncError("commit message must be one nonempty line")

    refreshed = build_plan(plan.source_root, plan.wiki_clone)
    if refreshed != plan:
        raise WikiSyncError("source or wiki clone changed after planning; review a new dry-run")
    if not plan.entries:
        return ApplyResult(plan, committed=False, pushed=False, commit=None)

    clone = plan.wiki_clone
    originals: dict[str, bytes | None] = {}
    for item in plan.entries:
        originals[item.path] = (
            _read_page(clone / item.path, f"wiki clone page {item.path}")
            if item.clone_sha256 is not None
            else None
        )

    committed = False
    try:
        for item in plan.entries:
            target = clone / item.path
            if item.operation in {"add", "change"}:
                source = plan.source_root / publication.WIKI_RELATIVE / item.path
                _atomic_write(target, _read_page(source, f"source page {item.path}"))
            else:
                current = _read_page(target, f"wiki clone page {item.path}")
                if _digest(current) != item.clone_sha256:
                    raise WikiSyncError(f"wiki clone page changed before deletion: {item.path}")
                target.unlink()

        names = tuple(item.path for item in plan.entries)
        _run_git(clone, ("add", "-A", "--", *names))
        expected = {item.path: item.operation for item in plan.entries}
        actual = _cached_plan(clone)
        if actual != expected:
            raise WikiSyncError(
                f"staged Wiki changes differ from reviewed plan: expected {expected}, found {actual}"
            )
        unstaged = _run_git(clone, ("diff", "--quiet", "--", *names), check=False)
        if unstaged.returncode != 0:
            raise WikiSyncError("unstaged Wiki changes appeared during synchronization")
        untracked = _run_git(clone, ("ls-files", "--others", "--exclude-standard", "-z")).stdout
        if untracked:
            raise WikiSyncError("unexpected untracked files appeared during synchronization")

        _run_git(
            clone,
            ("commit", "--no-gpg-sign", "-m", commit_message, "--", *names),
            timeout=45,
        )
        committed = True
        commit = _git_text(clone, ("rev-parse", "--verify", "HEAD^{commit}"), "new Wiki commit")
    except BaseException as error:
        if not committed:
            try:
                _rollback(clone, originals)
            except BaseException as rollback_error:
                raise WikiSyncError(
                    f"Wiki apply failed ({error}); automatic rollback also failed ({rollback_error})"
                ) from error
        if isinstance(error, WikiSyncError):
            raise
        raise WikiSyncError(f"Wiki apply failed: {error}") from error

    try:
        _run_git(
            clone,
            ("push", "--porcelain", "origin", f"HEAD:{plan.branch}"),
            timeout=45,
        )
    except WikiSyncError as error:
        raise WikiSyncError(
            f"Wiki commit {commit} was created locally, but push failed; inspect the clean clone and retry the push manually: {error}"
        ) from error
    return ApplyResult(plan, committed=True, pushed=True, commit=commit)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Plan or explicitly publish docs/wiki through a clean local clone of "
            f"{REPOSITORY}. The default is offline and read-only."
        )
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=ROOT,
        help="Swan Song source repository (default: script repository)",
    )
    parser.add_argument(
        "--wiki-clone",
        type=Path,
        required=True,
        help="explicit path to a clean local clone of RegionallyFamous/swansong-core.wiki",
    )
    parser.add_argument("--apply", action="store_true", help="copy, commit, and push the reviewed plan")
    parser.add_argument(
        "--confirm-publish",
        help=f"required with --apply; must exactly equal {CONFIRMATION}",
    )
    parser.add_argument(
        "--commit-message",
        default=DEFAULT_COMMIT_MESSAGE,
        help="single-line Wiki commit message",
    )
    parser.add_argument("--json", action="store_true", help="emit deterministic JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.confirm_publish is not None and not arguments.apply:
        print("wiki sync failed: --confirm-publish is valid only with --apply", file=sys.stderr)
        return 2
    try:
        plan = build_plan(arguments.source_root, arguments.wiki_clone)
        if arguments.apply:
            result = apply_plan(
                plan,
                arguments.confirm_publish or "",
                arguments.commit_message,
            )
            if arguments.json:
                print(json.dumps(result.document(), indent=2, sort_keys=True))
            elif result.pushed:
                print(
                    f"Published {len(plan.entries)} Wiki page operation(s) in commit {result.commit}."
                )
            else:
                print("Wiki clone already matches docs/wiki; no commit or push was needed.")
        elif arguments.json:
            print(json.dumps(plan.document(), indent=2, sort_keys=True))
        else:
            print(render_plan(plan), end="")
    except WikiSyncError as error:
        print(f"wiki sync failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
