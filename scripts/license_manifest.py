#!/usr/bin/env python3
"""Strict validation for Swan Song's packaged grant and notice map."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
from typing import Any


CORE_RELATIVE = pathlib.PurePosixPath("Cores/RegionallyFamous.SwanSong")
MANIFEST_FILENAME = "LICENSE-MANIFEST.json"
MANIFEST_MAGIC = "SWAN_SONG_LICENSE_MANIFEST_V1"
CORE_ID = "RegionallyFamous.SwanSong"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
LEGACY_TEST_PREFIXES = (
    "testroms/spritepriority/",
    "testroms/timingtest/",
    "testroms/windowtest/",
)


class StrictJsonError(ValueError):
    """JSON used duplicate members or non-standard numeric constants."""


def _strict_json_loads(value: str) -> Any:
    def object_without_duplicates(
        members: list[tuple[str, Any]],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, member_value in members:
            if name in result:
                raise StrictJsonError(f"duplicate object member {name!r}")
            result[name] = member_value
        return result

    def reject_nonstandard_constant(constant: str) -> None:
        raise StrictJsonError(f"non-standard JSON constant {constant!r}")

    return json.loads(
        value,
        object_pairs_hook=object_without_duplicates,
        parse_constant=reject_nonstandard_constant,
    )


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be an object")
    return value


def _exact(
    value: Any, where: str, members: set[str]
) -> dict[str, Any]:
    result = _object(value, where)
    missing = members - result.keys()
    unknown = result.keys() - members
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if unknown:
            details.append("unknown " + ", ".join(sorted(unknown)))
        raise ValueError(f"{where} has invalid members ({'; '.join(details)})")
    return result


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{where} must be a nonempty string")
    if any(ord(character) < 0x20 for character in value):
        raise ValueError(f"{where} contains a control character")
    return value


def _text_list(value: Any, where: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{where} must be an array")
    if not allow_empty and not value:
        raise ValueError(f"{where} must not be empty")
    result = [_text(member, f"{where}[{index}]") for index, member in enumerate(value)]
    if len(result) != len(set(result)):
        raise ValueError(f"{where} must not contain duplicates")
    return result


def _sha256(value: Any, where: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{where} must be a lowercase SHA-256 digest")
    return value


def _commit(value: Any, where: str, *, allow_null: bool = False) -> str | None:
    if value is None and allow_null:
        return None
    if not isinstance(value, str) or COMMIT_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{where} must be a lowercase 40-hex commit")
    return value


def _filename(value: Any, where: str) -> str:
    result = _text(value, where)
    path = pathlib.PurePosixPath(result)
    if (
        "\\" in result
        or path.is_absolute()
        or len(path.parts) != 1
        or path.parts[0] in {".", ".."}
    ):
        raise ValueError(f"{where} must be a plain filename")
    return result


def _review(
    value: Any,
    where: str,
    *,
    has_license_expression: bool,
) -> tuple[str, str | None]:
    status = value["review_status"]
    blocker = value["blocker"]
    if status not in {"documented", "review_required"}:
        raise ValueError(
            f"{where}.review_status must be documented or review_required"
        )
    if status == "documented":
        if blocker is not None:
            raise ValueError(f"{where}.blocker must be null when documented")
        if has_license_expression and value["license_expression"] == "NOASSERTION":
            raise ValueError(
                f"{where} cannot be documented with license_expression NOASSERTION"
            )
        return status, None
    return status, _text(blocker, f"{where}.blocker")


def validate_license_manifest(
    dist: pathlib.Path,
    *,
    source_root: pathlib.Path | None = None,
    require_release_ready: bool = False,
) -> dict[str, Any]:
    """Validate notice identities, review state, and optional source assets."""

    core = dist / pathlib.Path(*CORE_RELATIVE.parts)
    path = core / MANIFEST_FILENAME
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"license manifest must be a regular file: {path}")
    manifest_bytes = path.read_bytes()
    try:
        document = _strict_json_loads(manifest_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, StrictJsonError) as error:
        raise ValueError(f"invalid license manifest {path}: {error}") from error

    top = _exact(document, "license manifest", {"license_manifest"})
    body = _exact(
        top["license_manifest"],
        "license manifest.license_manifest",
        {
            "magic",
            "core_id",
            "package_notice_files",
            "components",
            "requirements",
            "release_gate",
            "legacy_test_assets",
        },
    )
    if body["magic"] != MANIFEST_MAGIC:
        raise ValueError(f"license manifest magic must be {MANIFEST_MAGIC}")
    if body["core_id"] != CORE_ID:
        raise ValueError(f"license manifest core_id must be {CORE_ID}")

    notices_value = body["package_notice_files"]
    if not isinstance(notices_value, list) or not notices_value:
        raise ValueError("license manifest package_notice_files must be a nonempty array")
    notices: dict[str, str] = {}
    for index, raw_notice in enumerate(notices_value):
        where = f"license manifest package_notice_files[{index}]"
        notice = _exact(raw_notice, where, {"filename", "sha256"})
        filename = _filename(notice["filename"], f"{where}.filename")
        digest = _sha256(notice["sha256"], f"{where}.sha256")
        if filename in notices:
            raise ValueError(f"license manifest notice is duplicated: {filename}")
        notice_path = core / filename
        if notice_path.is_symlink() or not notice_path.is_file():
            raise ValueError(f"packaged notice must be a regular file: {filename}")
        actual = hashlib.sha256(notice_path.read_bytes()).hexdigest()
        if actual != digest:
            raise ValueError(
                f"packaged notice SHA-256 does not match manifest: {filename}"
            )
        notices[filename] = digest
    if list(notices) != sorted(notices):
        raise ValueError("license manifest package_notice_files must be sorted")

    components_value = body["components"]
    if not isinstance(components_value, list) or not components_value:
        raise ValueError("license manifest components must be a nonempty array")
    ids: set[str] = set()
    unresolved: set[str] = set()
    for index, raw_component in enumerate(components_value):
        where = f"license manifest components[{index}]"
        component = _exact(
            raw_component,
            where,
            {
                "id",
                "scope",
                "origin",
                "license_expression",
                "notice_files",
                "evidence",
                "review_status",
                "blocker",
            },
        )
        component_id = _text(component["id"], f"{where}.id")
        if component_id in ids:
            raise ValueError(f"license manifest id is duplicated: {component_id}")
        ids.add(component_id)
        _text_list(component["scope"], f"{where}.scope")
        origin = _exact(
            component["origin"],
            f"{where}.origin",
            {"repository", "commit", "paths"},
        )
        repository = _text(origin["repository"], f"{where}.origin.repository")
        if not repository.startswith("https://"):
            raise ValueError(f"{where}.origin.repository must use https")
        _commit(origin["commit"], f"{where}.origin.commit", allow_null=True)
        _text_list(origin["paths"], f"{where}.origin.paths")
        _text(component["license_expression"], f"{where}.license_expression")
        notice_files = _text_list(
            component["notice_files"], f"{where}.notice_files", allow_empty=True
        )
        unknown_notices = set(notice_files) - notices.keys()
        if unknown_notices:
            raise ValueError(
                f"{where}.notice_files references unknown package notices: "
                + ", ".join(sorted(unknown_notices))
            )
        _text_list(component["evidence"], f"{where}.evidence")
        status, _ = _review(
            component, where, has_license_expression=True
        )
        if status == "review_required":
            unresolved.add(component_id)

    requirements_value = body["requirements"]
    if not isinstance(requirements_value, list) or not requirements_value:
        raise ValueError("license manifest requirements must be a nonempty array")
    for index, raw_requirement in enumerate(requirements_value):
        where = f"license manifest requirements[{index}]"
        requirement = _exact(
            raw_requirement,
            where,
            {"id", "evidence", "review_status", "blocker"},
        )
        requirement_id = _text(requirement["id"], f"{where}.id")
        if requirement_id in ids:
            raise ValueError(f"license manifest id is duplicated: {requirement_id}")
        ids.add(requirement_id)
        _text_list(requirement["evidence"], f"{where}.evidence")
        status, _ = _review(
            requirement, where, has_license_expression=False
        )
        if status == "review_required":
            unresolved.add(requirement_id)

    gate = _exact(
        body["release_gate"],
        "license manifest release_gate",
        {"licensing_review_complete", "unresolved_ids"},
    )
    complete = gate["licensing_review_complete"]
    if not isinstance(complete, bool):
        raise ValueError(
            "license manifest release_gate.licensing_review_complete must be boolean"
        )
    unresolved_ids = _text_list(
        gate["unresolved_ids"],
        "license manifest release_gate.unresolved_ids",
        allow_empty=True,
    )
    if unresolved_ids != sorted(unresolved_ids):
        raise ValueError("license manifest unresolved_ids must be sorted")
    if set(unresolved_ids) != unresolved:
        raise ValueError(
            "license manifest unresolved_ids do not match review_required items"
        )
    if complete != (not unresolved):
        raise ValueError(
            "license manifest licensing_review_complete does not match unresolved_ids"
        )

    legacy_value = body["legacy_test_assets"]
    if not isinstance(legacy_value, list) or len(legacy_value) != 19:
        raise ValueError("license manifest must inventory exactly 19 legacy test assets")
    legacy: dict[str, str] = {}
    for index, raw_asset in enumerate(legacy_value):
        where = f"license manifest legacy_test_assets[{index}]"
        asset = _exact(
            raw_asset, where, {"path", "sha256", "introduced_commit"}
        )
        asset_path = _text(asset["path"], f"{where}.path")
        pure_path = pathlib.PurePosixPath(asset_path)
        if (
            pure_path.is_absolute()
            or ".." in pure_path.parts
            or not asset_path.startswith(LEGACY_TEST_PREFIXES)
        ):
            raise ValueError(f"{where}.path is outside the legacy test roots")
        if asset_path in legacy:
            raise ValueError(f"legacy test asset is duplicated: {asset_path}")
        legacy[asset_path] = _sha256(asset["sha256"], f"{where}.sha256")
        _commit(asset["introduced_commit"], f"{where}.introduced_commit")
    if list(legacy) != sorted(legacy):
        raise ValueError("license manifest legacy_test_assets must be sorted")

    if source_root is not None:
        root = source_root.resolve()
        actual_paths: set[str] = set()
        for prefix in LEGACY_TEST_PREFIXES:
            directory = root / prefix.rstrip("/")
            if not directory.is_dir():
                raise ValueError(f"legacy test root is missing: {prefix}")
            for asset_path in directory.rglob("*"):
                if asset_path.is_symlink() or not asset_path.is_file():
                    raise ValueError(f"legacy test asset must be a regular file: {asset_path}")
                relative = asset_path.relative_to(root).as_posix()
                actual_paths.add(relative)
                actual_digest = hashlib.sha256(asset_path.read_bytes()).hexdigest()
                if legacy.get(relative) != actual_digest:
                    raise ValueError(
                        f"legacy test asset identity is absent or changed: {relative}"
                    )
        if actual_paths != legacy.keys():
            raise ValueError(
                "license manifest legacy test inventory does not match source tree"
            )

    if require_release_ready and not complete:
        raise ValueError(
            "license manifest review is not complete: " + ", ".join(unresolved_ids)
        )

    return {
        "magic": MANIFEST_MAGIC,
        "manifest_filename": MANIFEST_FILENAME,
        "manifest_size": len(manifest_bytes),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "core_id": CORE_ID,
        "package_notice_count": len(notices),
        "component_count": len(components_value),
        "requirement_count": len(requirements_value),
        "legacy_test_asset_count": len(legacy),
        "licensing_review_complete": complete,
        "unresolved_ids": unresolved_ids,
    }


def main() -> None:
    root = pathlib.Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=pathlib.Path, default=root / "dist")
    parser.add_argument("--source-root", type=pathlib.Path, default=root)
    parser.add_argument("--require-release-ready", action="store_true")
    arguments = parser.parse_args()
    try:
        summary = validate_license_manifest(
            arguments.dist,
            source_root=arguments.source_root,
            require_release_ready=arguments.require_release_ready,
        )
    except ValueError as error:
        raise SystemExit(f"license manifest validation failed: {error}") from error
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
