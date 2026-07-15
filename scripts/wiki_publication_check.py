#!/usr/bin/env python3
"""Offline, read-only publication audit for the Swan Song GitHub Wiki.

The repository copy under ``docs/wiki`` is the reviewable source.  This tool
checks its exact page manifest and internal links, verifies README wiki links,
and optionally compares it with an already-cloned GitHub Wiki worktree.  It
has no network or filesystem-write path: it never copies, deletes, commits, or
pushes files.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import difflib
import html
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import unicodedata
from typing import Iterable, Sequence
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
WIKI_RELATIVE = Path("docs/wiki")
README_RELATIVE = Path("README.md")
REPOSITORY = "RegionallyFamous/swansong-core"
MAX_MARKDOWN_BYTES = 2 * 1024 * 1024

WIKI_MANIFEST = (
    "Architecture.md",
    "Build-and-Test.md",
    "Compatibility-and-Current-Limits.md",
    "Controls-and-Settings.md",
    "Developer-Hub.md",
    "Home.md",
    "Install-Swan-Song.md",
    "Playing-Games.md",
    "Saves-and-Migration.md",
    "Troubleshooting-and-Bug-Reports.md",
    "_Sidebar.md",
)

README_REQUIRED_WIKI_PAGES = (
    "Compatibility-and-Current-Limits",
    "Controls-and-Settings",
    "Developer-Hub",
    "Install-Swan-Song",
    "Playing-Games",
    "Saves-and-Migration",
    "Troubleshooting-and-Bug-Reports",
)

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
_EXPLICIT_ANCHOR = re.compile(
    r"<a\s+[^>]*(?:id|name)\s*=\s*['\"]([^'\"]+)['\"][^>]*>", re.IGNORECASE
)
_INLINE_LINK = re.compile(
    r"(?<!!)\[[^\]]*\]\(\s*(?:<([^>\n]+)>|([^\s)\n]+))"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)"
)
_REFERENCE_DEFINITION = re.compile(
    r"^\s{0,3}\[([^\]]+)\]:\s*(?:<([^>\n]+)>|([^\s]+))",
    re.IGNORECASE | re.MULTILINE,
)
_REFERENCE_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\[([^\]]*)\]")
_AUTOLINK = re.compile(r"<(https://github\.com/[^>\s]+)>")
_INLINE_CODE = re.compile(r"`+[^`]*`+")


class PublicationCheckError(ValueError):
    """The requested source or wiki-clone root cannot be audited safely."""


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    location: str
    message: str


@dataclass(frozen=True)
class Link:
    origin: PurePosixPath
    line: int
    target: str


@dataclass
class PublicationReport:
    source_root: Path
    findings: list[Finding]
    readme_wiki_pages: tuple[str, ...]
    repository_targets: tuple[str, ...]
    wiki_clone: Path | None = None
    clone_clean: bool | None = None
    clone_differences: tuple[str, ...] = ()
    sync_diff: str = ""

    @property
    def ok(self) -> bool:
        return not any(item.severity == "ERROR" for item in self.findings)

    def document(self) -> dict[str, object]:
        return {
            "status": "ready" if self.ok else "needs_attention",
            "read_only": True,
            "network_access": False,
            "source_root": str(self.source_root),
            "wiki_manifest": list(WIKI_MANIFEST),
            "readme_wiki_pages": list(self.readme_wiki_pages),
            "repository_targets": list(self.repository_targets),
            "wiki_clone": str(self.wiki_clone) if self.wiki_clone else None,
            "clone_clean": self.clone_clean,
            "clone_differences": list(self.clone_differences),
            "findings": [asdict(item) for item in self.findings],
            "sync_diff": self.sync_diff,
            "publication_performed": False,
        }


def _safe_root(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise PublicationCheckError(
            f"{label} must be an existing, nonsymlink directory: {path}"
        )
    try:
        return path.resolve(strict=True)
    except OSError as error:
        raise PublicationCheckError(f"cannot resolve {label}: {error}") from error


def _read_regular_markdown(path: Path, root: Path, label: str) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise PublicationCheckError(f"{label} escapes its supplied root: {path}") from error

    current = root
    for part in relative.parts:
        current = current / part
        try:
            metadata = os.stat(current, follow_symlinks=False)
        except OSError as error:
            raise PublicationCheckError(f"cannot inspect {label}: {error}") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise PublicationCheckError(f"{label} must not traverse a symlink: {path}")
    if not stat.S_ISREG(metadata.st_mode):
        raise PublicationCheckError(f"{label} is not a regular file: {path}")
    if metadata.st_size > MAX_MARKDOWN_BYTES:
        raise PublicationCheckError(
            f"{label} exceeds the {MAX_MARKDOWN_BYTES}-byte audit limit: {path}"
        )
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise PublicationCheckError(f"cannot read UTF-8 {label}: {error}") from error


def _markdown_lines(text: str) -> Iterable[tuple[int, str]]:
    """Yield Markdown outside fenced code blocks."""

    fence_character: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        fence = _FENCE.match(line)
        if fence:
            character = fence.group(1)[0]
            if fence_character is None:
                fence_character = character
            elif fence_character == character:
                fence_character = None
            continue
        if fence_character is None:
            yield number, line


def _markdown_mask(text: str) -> str:
    """Blank fenced code while preserving offsets and line numbers."""

    output: list[str] = []
    fence_character: str | None = None
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        ending = line[len(content) :]
        fence = _FENCE.match(content)
        if fence:
            character = fence.group(1)[0]
            if fence_character is None:
                fence_character = character
            elif fence_character == character:
                fence_character = None
            output.append(" " * len(content) + ending)
        elif fence_character is None:
            output.append(content + ending)
        else:
            output.append(" " * len(content) + ending)
    return "".join(output)


def _reference_definitions(text: str) -> dict[str, str]:
    definitions: dict[str, str] = {}
    for match in _REFERENCE_DEFINITION.finditer(_markdown_mask(text)):
        key = " ".join(match.group(1).casefold().split())
        definitions[key] = match.group(2) or match.group(3)
    return definitions


def _links(text: str, origin: PurePosixPath) -> list[Link]:
    definitions = _reference_definitions(text)
    result: list[Link] = []
    seen: set[tuple[int, str]] = set()
    markdown = _markdown_mask(text)
    markdown = _INLINE_CODE.sub(lambda match: " " * len(match.group(0)), markdown)

    def add(match: re.Match[str], target: str) -> None:
        number = markdown.count("\n", 0, match.start()) + 1
        key = (number, target)
        if key not in seen:
            result.append(Link(origin, number, target))
            seen.add(key)

    for match in _INLINE_LINK.finditer(markdown):
        add(match, match.group(1) or match.group(2))
    for match in _REFERENCE_LINK.finditer(markdown):
        reference = match.group(2) or match.group(1)
        key_name = " ".join(reference.casefold().split())
        target = definitions.get(key_name)
        if target is not None:
            add(match, target)
    for match in _AUTOLINK.finditer(markdown):
        add(match, match.group(1))
    result.sort(key=lambda item: (item.line, item.target))
    return result


def _github_heading_slug(text: str) -> str:
    value = html.unescape(text)
    value = re.sub(r"<[^>]*>", "", value)
    value = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = value.replace("`", "").replace("*", "")
    value = "".join(
        character
        for character in value.casefold()
        if character in {" ", "-", "_"}
        or unicodedata.category(character)[0] in {"L", "N"}
    )
    return re.sub(r"\s+", "-", value.strip())


def _anchors(text: str) -> set[str]:
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    for _, line in _markdown_lines(text):
        for explicit in _EXPLICIT_ANCHOR.findall(line):
            anchors.add(unquote(explicit))
        match = _HEADING.match(line)
        if not match:
            continue
        heading = re.sub(r"\s+#+\s*$", "", match.group(2))
        base = _github_heading_slug(heading)
        if not base:
            continue
        count = counts.get(base, 0)
        counts[base] = count + 1
        anchors.add(base if count == 0 else f"{base}-{count}")
    return anchors


def _normalized_repository_path(raw: str) -> PurePosixPath | None:
    decoded = unquote(raw)
    candidate = PurePosixPath(decoded)
    if (
        not decoded
        or decoded.startswith("/")
        or "\\" in decoded
        or "\x00" in decoded
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        return None
    return candidate


def _file_target(
    source_root: Path,
    relative: PurePosixPath,
    fragment: str,
    link: Link,
    findings: list[Finding],
    documents: dict[PurePosixPath, str],
) -> None:
    location = f"{link.origin.as_posix()}:{link.line}"
    candidate = source_root.joinpath(*relative.parts)
    try:
        candidate.relative_to(source_root)
    except ValueError:
        findings.append(
            Finding("ERROR", "relative-target-escape", location, f"target escapes source tree: {link.target}")
        )
        return
    if candidate.is_symlink() or not candidate.is_file():
        findings.append(
            Finding("ERROR", "missing-local-target", location, f"target is missing from supplied source tree: {relative.as_posix()}")
        )
        return
    text = documents.get(relative)
    if candidate.suffix.casefold() == ".md" and text is None:
        try:
            text = _read_regular_markdown(candidate, source_root, relative.as_posix())
        except PublicationCheckError as error:
            findings.append(Finding("ERROR", "unsafe-local-target", location, str(error)))
            return
        documents[relative] = text
    elif candidate.suffix.casefold() != ".md":
        current = source_root
        try:
            for part in relative.parts:
                current = current / part
                metadata = os.stat(current, follow_symlinks=False)
                if stat.S_ISLNK(metadata.st_mode):
                    raise PublicationCheckError(
                        f"target must not traverse a symlink: {relative.as_posix()}"
                    )
        except (OSError, PublicationCheckError) as error:
            findings.append(Finding("ERROR", "unsafe-local-target", location, str(error)))
            return
    if not fragment:
        return
    if text is None:
        findings.append(
            Finding("ERROR", "unsupported-fragment-target", location, f"cannot verify a heading fragment on non-Markdown target: {relative.as_posix()}#{fragment}")
        )
        return
    decoded_fragment = unquote(fragment)
    if decoded_fragment not in _anchors(text):
        findings.append(
            Finding("ERROR", "missing-heading-fragment", location, f"heading fragment does not exist: {relative.as_posix()}#{decoded_fragment}")
        )


def _audit_link(
    link: Link,
    source_root: Path,
    documents: dict[PurePosixPath, str],
    findings: list[Finding],
    readme_pages: set[str],
    repository_targets: set[str],
) -> None:
    parsed = urlsplit(link.target)
    location = f"{link.origin.as_posix()}:{link.line}"
    wiki_path_prefix = f"/{REPOSITORY}/wiki/"
    blob_path_prefix = f"/{REPOSITORY}/blob/main/"

    if parsed.scheme or parsed.netloc:
        if parsed.scheme != "https" or parsed.netloc.casefold() != "github.com":
            return
        if parsed.path.startswith(wiki_path_prefix):
            page = unquote(parsed.path[len(wiki_path_prefix) :]).strip("/")
            if "/" in page or not page:
                findings.append(
                    Finding("ERROR", "invalid-wiki-target", location, f"wiki link does not name one page: {link.target}")
                )
                return
            if link.origin == PurePosixPath(README_RELATIVE.as_posix()):
                readme_pages.add(page)
            page_file = f"{page}.md"
            if page_file not in WIKI_MANIFEST:
                findings.append(
                    Finding("ERROR", "missing-wiki-target", location, f"wiki page is outside the exact manifest: {page}")
                )
                return
            relative = PurePosixPath(WIKI_RELATIVE.as_posix()) / page_file
            _file_target(source_root, relative, parsed.fragment, link, findings, documents)
            return
        if parsed.path.startswith(blob_path_prefix):
            raw = parsed.path[len(blob_path_prefix) :]
            relative = _normalized_repository_path(raw)
            if relative is None:
                findings.append(
                    Finding("ERROR", "invalid-blob-main-target", location, f"blob/main target is not a normalized repository path: {link.target}")
                )
                return
            repository_targets.add(relative.as_posix())
            _file_target(source_root, relative, parsed.fragment, link, findings, documents)
        return

    raw_path = unquote(parsed.path)
    if not raw_path:
        relative = link.origin
    elif raw_path.startswith("/") or "\\" in raw_path or "\x00" in raw_path:
        findings.append(
            Finding("ERROR", "invalid-relative-target", location, f"local link is not a safe relative path: {link.target}")
        )
        return
    else:
        base = link.origin.parent
        path = PurePosixPath(raw_path)
        if link.origin.parts[:2] == WIKI_RELATIVE.parts and not path.suffix:
            path = path.with_suffix(".md")
        parts: list[str] = []
        for part in (*base.parts, *path.parts):
            if part in {"", "."}:
                continue
            if part == "..":
                if not parts:
                    findings.append(
                        Finding("ERROR", "relative-target-escape", location, f"target escapes source tree: {link.target}")
                    )
                    return
                parts.pop()
            else:
                parts.append(part)
        relative = PurePosixPath(*parts)
    _file_target(source_root, relative, parsed.fragment, link, findings, documents)


def _manifest_entries(directory: Path, ignore_git: bool = False) -> tuple[str, ...]:
    try:
        entries = [entry.name for entry in directory.iterdir()]
    except OSError as error:
        raise PublicationCheckError(f"cannot enumerate {directory}: {error}") from error
    if ignore_git:
        entries = [name for name in entries if name != ".git"]
    return tuple(sorted(entries))


def _check_manifest(
    entries: tuple[str, ...], label: str, findings: list[Finding]
) -> None:
    expected = set(WIKI_MANIFEST)
    actual = set(entries)
    for name in sorted(expected - actual):
        findings.append(Finding("ERROR", "wiki-manifest-missing", label, f"missing required wiki page: {name}"))
    for name in sorted(actual - expected):
        findings.append(Finding("ERROR", "wiki-manifest-extra", label, f"unexpected entry will not be deleted automatically: {name}"))


def _git_clean(worktree: Path, findings: list[Finding]) -> bool:
    if not (worktree / ".git").exists():
        findings.append(
            Finding("ERROR", "wiki-clone-not-git", str(worktree), "supplied wiki comparison directory is not a Git worktree")
        )
        return False
    environment = dict(os.environ)
    environment.update({"GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"})
    try:
        result = subprocess.run(
            [
                "git",
                "-c",
                "core.fsmonitor=false",
                "-C",
                str(worktree),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            timeout=15,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as error:
        findings.append(Finding("ERROR", "wiki-clone-git-error", str(worktree), f"cannot verify clone cleanliness: {error}"))
        return False
    if result.returncode != 0:
        detail = result.stderr.strip() or f"git status exited {result.returncode}"
        findings.append(Finding("ERROR", "wiki-clone-git-error", str(worktree), f"cannot verify clone cleanliness: {detail}"))
        return False
    dirty = tuple(line for line in result.stdout.splitlines() if line)
    if dirty:
        findings.append(
            Finding("ERROR", "wiki-clone-dirty", str(worktree), f"supplied wiki worktree is not clean ({len(dirty)} status entr{'y' if len(dirty) == 1 else 'ies'})")
        )
        return False
    return True


def _compare_clone(
    wiki_clone: Path,
    source_root: Path,
    source_documents: dict[PurePosixPath, str],
    findings: list[Finding],
) -> tuple[bool, tuple[str, ...], str]:
    clone = _safe_root(wiki_clone, "wiki clone")
    clean = _git_clean(clone, findings)
    entries = _manifest_entries(clone, ignore_git=True)
    _check_manifest(entries, "wiki clone", findings)
    differences: list[str] = []
    diff_lines: list[str] = []
    for name in WIKI_MANIFEST:
        source_relative = PurePosixPath(WIKI_RELATIVE.as_posix()) / name
        source_text = source_documents.get(source_relative)
        if source_text is None:
            continue
        published = clone / name
        if not published.exists() or published.is_symlink() or not published.is_file():
            differences.append(name)
            if name in entries:
                findings.append(
                    Finding(
                        "ERROR",
                        "unsafe-wiki-clone-page",
                        name,
                        "wiki clone page must be a regular nonsymlink file",
                    )
                )
            diff_lines.extend(
                difflib.unified_diff(
                    [],
                    source_text.splitlines(keepends=True),
                    fromfile="/dev/null",
                    tofile=f"source/docs/wiki/{name}",
                )
            )
            continue
        try:
            clone_text = _read_regular_markdown(published, clone, f"wiki clone page {name}")
        except PublicationCheckError as error:
            findings.append(Finding("ERROR", "unsafe-wiki-clone-page", name, str(error)))
            continue
        if clone_text == source_text:
            continue
        differences.append(name)
        diff_lines.extend(
            difflib.unified_diff(
                clone_text.splitlines(keepends=True),
                source_text.splitlines(keepends=True),
                fromfile=f"wiki-clone/{name}",
                tofile=f"source/docs/wiki/{name}",
            )
        )
    return clean, tuple(differences), "".join(diff_lines)


def check_publication(
    source_root: Path = ROOT, wiki_clone: Path | None = None
) -> PublicationReport:
    source = _safe_root(source_root, "source root")
    wiki = source / WIKI_RELATIVE
    if wiki.is_symlink() or not wiki.is_dir():
        raise PublicationCheckError(f"wiki source must be a nonsymlink directory: {wiki}")

    findings: list[Finding] = []
    entries = _manifest_entries(wiki)
    _check_manifest(entries, WIKI_RELATIVE.as_posix(), findings)

    documents: dict[PurePosixPath, str] = {}
    for name in WIKI_MANIFEST:
        relative = PurePosixPath(WIKI_RELATIVE.as_posix()) / name
        path = source.joinpath(*relative.parts)
        if name not in entries:
            continue
        try:
            documents[relative] = _read_regular_markdown(path, source, relative.as_posix())
        except PublicationCheckError as error:
            findings.append(Finding("ERROR", "unsafe-wiki-page", relative.as_posix(), str(error)))

    readme_relative = PurePosixPath(README_RELATIVE.as_posix())
    try:
        documents[readme_relative] = _read_regular_markdown(
            source / README_RELATIVE, source, README_RELATIVE.as_posix()
        )
    except PublicationCheckError as error:
        findings.append(Finding("ERROR", "unsafe-readme", README_RELATIVE.as_posix(), str(error)))

    readme_pages: set[str] = set()
    repository_targets: set[str] = set()
    primary_documents = [readme_relative] + [
        PurePosixPath(WIKI_RELATIVE.as_posix()) / name for name in WIKI_MANIFEST
    ]
    for origin in primary_documents:
        text = documents.get(origin)
        if text is None:
            continue
        for link in _links(text, origin):
            _audit_link(
                link,
                source,
                documents,
                findings,
                readme_pages,
                repository_targets,
            )

    required = set(README_REQUIRED_WIKI_PAGES)
    for page in sorted(required - readme_pages):
        findings.append(
            Finding("ERROR", "readme-wiki-target-missing", README_RELATIVE.as_posix(), f"README does not link required wiki page: {page}")
        )

    report = PublicationReport(
        source_root=source,
        findings=findings,
        readme_wiki_pages=tuple(sorted(readme_pages)),
        repository_targets=tuple(sorted(repository_targets)),
    )
    if wiki_clone is not None:
        clone = _safe_root(wiki_clone, "wiki clone")
        clean, differences, sync_diff = _compare_clone(
            clone, source, documents, findings
        )
        report.wiki_clone = clone
        report.clone_clean = clean
        report.clone_differences = differences
        report.sync_diff = sync_diff
    return report


def render_report(report: PublicationReport) -> str:
    status = "READY" if report.ok else "NEEDS ATTENTION"
    lines = [
        f"WIKI PUBLICATION CHECK: {status}",
        "Mode: offline read-only; no network access and no filesystem writes",
        f"Wiki source manifest: {len(WIKI_MANIFEST)} required pages",
        f"README wiki targets: {len(report.readme_wiki_pages)} unique pages",
        f"Repository blob/main targets checked: {len(report.repository_targets)}",
    ]
    if report.wiki_clone is None:
        lines.append("Wiki clone comparison: not requested")
    else:
        cleanliness = "clean" if report.clone_clean else "NOT CLEAN"
        lines.append(f"Wiki clone comparison: {cleanliness}")
        lines.append(
            "Pages different from supplied clone: "
            + (", ".join(report.clone_differences) or "none")
        )
    if report.findings:
        lines.append("")
        for item in report.findings:
            lines.append(
                f"{item.severity} [{item.code}] {item.location}: {item.message}"
            )
    if report.wiki_clone is not None:
        lines.extend(("", "DRY-RUN CONTENT DIFF"))
        lines.append(report.sync_diff.rstrip() or "No page-content differences.")
    lines.extend(
        (
            "",
            "SAFE SYNCHRONIZATION ORDER (INSTRUCTIONS ONLY)",
            "1. Merge the reviewed source documentation and every blob/main target to main first.",
            "2. Re-run this check against a fresh, clean clone of the wiki.",
            "3. Review the complete 11-page dry-run diff and any unexpected clone entries.",
            "4. Copy and publish only after human approval; this checker never copies, deletes, commits, or pushes.",
        )
    )
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Offline, read-only Swan Song wiki publication audit. It never "
            "copies, deletes, commits, pushes, or accesses the network."
        )
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=ROOT,
        help="repository source tree to audit (default: script repository)",
    )
    parser.add_argument(
        "--wiki-clone",
        type=Path,
        help="optional already-cloned, clean wiki worktree to compare read-only",
    )
    parser.add_argument("--json", action="store_true", help="emit deterministic JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        report = check_publication(arguments.source_root, arguments.wiki_clone)
    except PublicationCheckError as error:
        print(f"wiki publication check failed: {error}", file=sys.stderr)
        return 2
    if arguments.json:
        print(json.dumps(report.document(), indent=2, sort_keys=True))
    else:
        print(render_report(report), end="")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
