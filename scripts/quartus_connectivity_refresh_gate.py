#!/usr/bin/env python3
"""Require a complete otherwise-clean Quartus build before policy refresh."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import stat
import sys
from typing import Optional, Sequence

import quartus_connectivity_policy as connectivity
import quartus_connectivity_source_closure as source_closure
import quartus_fit_audit as fit_audit


SOURCE_DRIFT = re.compile(
    r"bound connectivity source changed without review: (.+)\Z"
)
REMOVED_SOURCE = re.compile(
    r"bound connectivity source is not a regular file: (.+)\Z"
)


class RefreshGateError(RuntimeError):
    """The fit failed for more than the exact refreshable policy drift."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _policy_path(source_root: Path, selected: Path) -> Path:
    source_root = source_root.resolve(strict=True)
    expected = source_root / connectivity.POLICY_RELATIVE
    candidate = selected if selected.is_absolute() else source_root / selected
    try:
        metadata = candidate.lstat()
    except FileNotFoundError as error:
        raise RefreshGateError(f"connectivity policy does not exist: {candidate}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RefreshGateError(
            f"connectivity policy must be a regular nonsymlink file: {candidate}"
        )
    if candidate.resolve(strict=True) != expected.resolve(strict=True):
        raise RefreshGateError(
            "refresh audit must use the repository's exact connectivity policy path"
        )
    return candidate


def _current_closure(
    source_root: Path,
) -> tuple[dict[str, str], dict[str, object]]:
    try:
        return source_closure.current_bindings(source_root)
    except source_closure.ClosureError as error:
        raise RefreshGateError(
            f"current Quartus source closure is invalid: {error}"
        ) from error


def _require_exact_source_drift(
    policy: dict,
    source_root: Path,
) -> tuple[dict[str, object], dict[str, str]]:
    """Accept only source/closure drift emitted by the selected valid policy."""

    try:
        connectivity._validate_source_bindings(policy, source_root)  # noqa: SLF001
    except connectivity.PolicyError as error:
        message = str(error)
    else:
        raise RefreshGateError(
            "connectivity policy is current; refresh requires exact source-binding drift"
        )

    raw_bindings = policy["source_bindings"]
    changed = SOURCE_DRIFT.fullmatch(message)
    if changed is not None:
        relative = changed.group(1)
        expected = raw_bindings.get(relative)
        if not isinstance(expected, str):
            raise RefreshGateError(
                "source-drift rejection is not tied to the selected policy"
            )
        path = source_root / relative
        try:
            metadata = path.lstat()
        except FileNotFoundError as error:
            raise RefreshGateError(
                "changed source-drift rejection names a missing path"
            ) from error
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RefreshGateError(
                "changed source-drift rejection names a non-regular path"
            )
        actual = _sha256(path)
        if actual == expected:
            raise RefreshGateError(
                "source-drift rejection is not supported by an actual hash change"
            )
        current = {}
        for bound_relative in raw_bindings:
            bound_path = source_root / bound_relative
            try:
                bound_metadata = bound_path.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISREG(bound_metadata.st_mode) and not stat.S_ISLNK(
                bound_metadata.st_mode
            ):
                current[bound_relative] = _sha256(bound_path)
        return (
            {
                "status": "bound_source_changed",
                "path": relative,
                "expected_sha256": expected,
                "actual_sha256": actual,
            },
            current,
        )

    removed = REMOVED_SOURCE.fullmatch(message)
    if removed is not None:
        relative = removed.group(1)
        if relative not in raw_bindings or (source_root / relative).exists():
            raise RefreshGateError(
                "removed source-drift rejection is not tied to a missing policy path"
            )
        current, _ = _current_closure(source_root)
        if relative in current:
            raise RefreshGateError(
                "removed source remains in the current Quartus source closure"
            )
        return ({"status": "bound_source_removed", "path": relative}, current)

    if policy["magic"] == connectivity.UPGRADED_MAGIC:
        current, identity = _current_closure(source_root)
        expected_paths = set(raw_bindings)
        current_paths = set(current)
        missing = sorted(current_paths - expected_paths)
        unexpected = sorted(expected_paths - current_paths)
        incomplete_message = (
            "policy source bindings are not the complete Quartus closure: "
            f"missing={missing!r} unexpected={unexpected!r}"
        )
        if (
            message == "policy source-closure identity is not current and exact"
            and policy["source_closure"] != identity
        ):
            return ({"status": "source_closure_identity_changed"}, current)
        if message == incomplete_message and (missing or unexpected):
            return (
                {
                    "status": "source_closure_paths_changed",
                    "missing": missing,
                    "unexpected": unexpected,
                },
                current,
            )
        if (
            message == "policy source bindings do not match the complete closure"
            and raw_bindings != current
        ):
            return ({"status": "source_closure_bindings_changed"}, current)

    raise RefreshGateError(
        "connectivity policy was rejected for a non-refreshable reason: " + message
    )


def audit_refresh(
    artifacts: Path,
    source_root: Path,
    policy_path: Path,
) -> dict[str, object]:
    """Validate every candidate artifact while deferring only exact source drift."""

    source_root = source_root.resolve(strict=True)
    selected_policy = _policy_path(source_root, policy_path)
    policy, _, _ = connectivity._read_policy(  # noqa: SLF001
        selected_policy, source_root
    )
    drift, current_bindings = _require_exact_source_drift(policy, source_root)

    original_review = connectivity.review_report
    original_validate = connectivity._validate_source_bindings  # noqa: SLF001
    original_source_root = fit_audit.SOURCE_ROOT
    review_invoked = False

    def deferred_review(
        report_text: str,
        call_source_root: Path,
        policy_path: Optional[Path] = None,
    ) -> dict:
        nonlocal review_invoked
        if Path(call_source_root).resolve(strict=True) != source_root:
            raise connectivity.PolicyError(
                "refresh audit attempted connectivity review against another source root"
            )
        if policy_path is not None:
            raise connectivity.PolicyError(
                "refresh audit refuses an alternate connectivity policy"
            )
        review_invoked = True

        def deferred_bindings(selected: dict, selected_root: Path) -> dict[str, str]:
            if selected != policy or selected_root.resolve(strict=True) != source_root:
                raise connectivity.PolicyError(
                    "refresh audit source-binding deferral escaped its selected policy"
                )
            return current_bindings

        connectivity._validate_source_bindings = deferred_bindings  # type: ignore[attr-defined] # noqa: SLF001
        try:
            review = original_review(
                report_text,
                source_root,
                selected_policy,
            )
        finally:
            connectivity._validate_source_bindings = original_validate  # type: ignore[attr-defined] # noqa: SLF001
        review["accepted"] = True
        review["status"] = "deferred_exact_source_drift"
        review["deferred_source_drift"] = drift
        return review

    connectivity.review_report = deferred_review
    fit_audit.SOURCE_ROOT = source_root
    try:
        payload = fit_audit.audit(artifacts)
    finally:
        fit_audit.SOURCE_ROOT = original_source_root
        connectivity.review_report = original_review
        connectivity._validate_source_bindings = original_validate  # type: ignore[attr-defined] # noqa: SLF001

    if not review_invoked:
        raise RefreshGateError(
            "refresh audit did not encounter the exact Warning 12241 review path"
        )
    audit = payload.get("quartus_audit")
    if not isinstance(audit, dict) or audit.get("audit_pass") is not True:
        gates = audit.get("candidate_gates", {}) if isinstance(audit, dict) else {}
        failed = sorted(
            name
            for name, result in gates.items()
            if name
            not in {
                "compressed_bitstream",
                "dock_hardware",
                "no_connectivity_warnings",
                "pocket_hardware",
            }
            and result is not True
        )
        raise RefreshGateError(
            "non-connectivity Quartus candidate gates failed: "
            + (", ".join(failed) if failed else "invalid audit envelope")
        )
    exact_review = audit.get("connectivity_warnings", {}).get("exact_review", {})
    if (
        not isinstance(exact_review, dict)
        or exact_review.get("status") != "deferred_exact_source_drift"
        or exact_review.get("deferred_source_drift") != drift
    ):
        raise RefreshGateError("refresh audit did not retain its exact drift identity")
    return payload


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        audit_refresh(args.artifacts, args.source_root, args.policy)
    except (
        OSError,
        RefreshGateError,
        connectivity.PolicyError,
        fit_audit.AuditError,
    ) as error:
        print(f"quartus_connectivity_refresh_gate.py: {error}", file=sys.stderr)
        return 1
    print("Quartus refresh audit passed all non-connectivity candidate gates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
