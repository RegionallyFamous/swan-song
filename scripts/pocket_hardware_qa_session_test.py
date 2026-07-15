#!/usr/bin/env python3
"""Adversarial tests for the private physical-evidence session recorder."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import unittest
from unittest import mock

import pocket_hardware_qa as qa
import pocket_hardware_qa_session as session


CASE_ID = "pocket_horizontal_input"
STARTED = "2026-07-15T12:00:00Z"
CAPTURED_VIDEO = "2026-07-15T12:00:01Z"
CAPTURED_LOG = "2026-07-15T12:00:02Z"
COMPLETED = "2026-07-15T12:00:03Z"


class HardwareQASessionTests(unittest.TestCase):
    def setUp(self) -> None:
        # Reuse the reviewed synthetic private inventory builder without
        # subclassing or rediscovering its extensive verifier test suite.
        from pocket_hardware_qa_test import PocketHardwareQATest

        self.fixture = PocketHardwareQATest(
            "test_generated_manifest_is_valid_pending_and_rejected_for_acceptance"
        )
        self.fixture.setUp()
        self.root = self.fixture.root
        self.inventory = self.fixture.inventory
        self.manifest = self.fixture.manifest
        self.private = self.fixture.private
        self.original_manifest = self.manifest.read_bytes()

    def tearDown(self) -> None:
        self.fixture.doCleanups()
        self.fixture.tearDown()

    def start(self, *, apply: bool = True) -> dict:
        return session.start_case(
            inventory=self.inventory,
            manifest=self.manifest,
            case_id=CASE_ID,
            started_at=STARTED,
            rom_ids=["horizontal-sram"],
            controller_ids=["pocket"],
            apply=apply,
        )

    def source(self, name: str, payload: bytes) -> Path:
        path = self.private / name
        path.write_bytes(payload)
        return path

    @staticmethod
    def video_bytes(marker: bytes = b"A") -> bytes:
        from pocket_hardware_qa_test import VALID_MP4

        return VALID_MP4 + struct.pack(">I", 8 + len(marker)) + b"free" + marker

    def ingest_video(self, source: Path | None = None, *, apply: bool = True) -> dict:
        source = source or self.source("capture.mp4", self.video_bytes())
        return session.ingest_artifact(
            inventory=self.inventory,
            manifest=self.manifest,
            source=source,
            kind="video",
            label="physical controls capture",
            captured_at=CAPTURED_VIDEO,
            apply=apply,
        )

    def ingest_log(self, source: Path | None = None, *, apply: bool = True) -> dict:
        source = source or self.source(
            "operator.txt", b"physical Pocket input observations\n"
        )
        return session.ingest_artifact(
            inventory=self.inventory,
            manifest=self.manifest,
            source=source,
            kind="log",
            label="physical input operator log",
            captured_at=CAPTURED_LOG,
            apply=apply,
        )

    def result(
        self,
        *,
        status: str = "pass",
        completed_at: str = COMPLETED,
        checks: dict[str, bool] | None = None,
        extra: dict | None = None,
    ) -> Path:
        if checks is None:
            checks = {name: True for name in qa.CASE_BY_ID[CASE_ID].checks}
        value = {
            "magic": session.RESULT_MAGIC,
            "case_id": CASE_ID,
            "status": status,
            "completed_at": completed_at,
            "checks": checks,
            "notes": "Human-recorded physical observation; no result inferred.",
        }
        if extra:
            value.update(extra)
        path = self.private / "case-result.json"
        path.write_text(
            json.dumps({"hardware_qa_case_result": value}), encoding="utf-8"
        )
        return path

    def test_start_uses_private_sidecar_and_keeps_manifest_pending(self) -> None:
        active = self.start()
        self.assertEqual(self.manifest.read_bytes(), self.original_manifest)
        sidecar = self.manifest.parent / session.SESSION_FILENAME
        self.assertTrue(sidecar.is_file())
        self.assertEqual(stat.S_IMODE(sidecar.stat().st_mode), 0o600)
        self.assertEqual(active["active_case"]["case_id"], CASE_ID)
        generated = json.loads(self.manifest.read_text())["hardware_qa"]
        target = next(item for item in generated["cases"] if item["id"] == CASE_ID)
        self.assertEqual(target["status"], "pending")
        self.assertFalse(any(target["checks"].values()))

    def test_dry_run_never_creates_session(self) -> None:
        self.start(apply=False)
        self.assertFalse((self.manifest.parent / session.SESSION_FILENAME).exists())
        self.assertEqual(self.manifest.read_bytes(), self.original_manifest)

    def test_ingest_is_deterministic_no_clobber_and_structurally_valid(self) -> None:
        self.start()
        first = self.ingest_video()
        second = self.ingest_log()
        self.assertEqual(first["id"], f"{CASE_ID}-video-01")
        self.assertEqual(first["path"], f"files/{CASE_ID}/{CASE_ID}-video-01.mp4")
        self.assertEqual(second["id"], f"{CASE_ID}-log-01")
        destination = self.manifest.parent / first["path"]
        self.assertEqual(destination.read_bytes(), self.video_bytes())
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
        self.assertEqual(destination.stat().st_nlink, 1)
        self.assertEqual(first["size"], len(self.video_bytes()))
        with self.assertRaisesRegex(session.SessionError, "same source"):
            self.ingest_video(self.private / "capture.mp4")

    def test_truncated_video_with_valid_metadata_cannot_be_evidence(self) -> None:
        from pocket_hardware_qa_test import VALID_MP4

        self.start()
        cutoff = VALID_MP4.index(b"mdat") + 4
        source = self.source("truncated.mp4", VALID_MP4[:cutoff])
        with self.assertRaisesRegex(session.SessionError, "not decodable|no decoded"):
            self.ingest_video(source)

    def test_finish_requires_explicit_human_result_and_preserves_attestation(self) -> None:
        self.start()
        self.ingest_video()
        self.ingest_log()
        before = json.loads(self.manifest.read_text())["hardware_qa"]["attestation"]
        document = session.finish_case(
            inventory=self.inventory,
            manifest=self.manifest,
            result=self.result(),
            apply=True,
        )
        after = document["hardware_qa"]["attestation"]
        self.assertEqual(after, before)
        self.assertEqual(after, {
            "physical_hardware_observed": False,
            "results_not_inferred_from_simulation": False,
            "evidence_reviewed": False,
            "reviewer": None,
            "reviewed_at": None,
        })
        target = next(
            item for item in document["hardware_qa"]["cases"]
            if item["id"] == CASE_ID
        )
        self.assertEqual(target["status"], "pass")
        self.assertTrue(all(target["checks"].values()))
        self.assertEqual(target["rom_ids"], ["horizontal-sram"])
        self.assertEqual(target["controller_ids"], ["pocket"])
        self.assertFalse((self.manifest.parent / session.SESSION_FILENAME).exists())
        summary = qa.verify_manifest(
            self.manifest, self.inventory, require_pass=False
        )
        self.assertEqual(summary["artifacts"], 2)

    def test_explicit_failure_is_retained_but_never_accepted(self) -> None:
        self.start()
        self.ingest_video()
        checks = {name: True for name in qa.CASE_BY_ID[CASE_ID].checks}
        checks[qa.CASE_BY_ID[CASE_ID].checks[0]] = False
        document = session.finish_case(
            inventory=self.inventory,
            manifest=self.manifest,
            result=self.result(status="fail", checks=checks),
            apply=True,
        )
        target = next(
            item for item in document["hardware_qa"]["cases"]
            if item["id"] == CASE_ID
        )
        self.assertEqual(target["status"], "fail")
        with self.assertRaisesRegex(ValueError, "not accepted"):
            qa.verify_manifest(self.manifest, self.inventory, require_pass=True)

    def test_pass_refuses_missing_checks_and_missing_required_artifacts(self) -> None:
        self.start()
        self.ingest_video()
        incomplete = {name: True for name in qa.CASE_BY_ID[CASE_ID].checks}
        incomplete.pop(next(iter(incomplete)))
        before = self.manifest.read_bytes()
        with self.assertRaisesRegex(session.SessionError, "every exact check"):
            session.finish_case(
                inventory=self.inventory,
                manifest=self.manifest,
                result=self.result(checks=incomplete),
                apply=True,
            )
        self.assertEqual(self.manifest.read_bytes(), before)

        complete_result = self.result()
        with self.assertRaisesRegex(session.SessionError, "needs 1 artifact"):
            session.finish_case(
                inventory=self.inventory,
                manifest=self.manifest,
                result=complete_result,
                apply=True,
            )
        self.assertEqual(self.manifest.read_bytes(), before)

    def test_result_cannot_smuggle_reviewer_or_attestation_authority(self) -> None:
        self.start()
        self.ingest_video()
        self.ingest_log()
        with self.assertRaisesRegex(session.SessionError, "invalid members"):
            session.finish_case(
                inventory=self.inventory,
                manifest=self.manifest,
                result=self.result(extra={"reviewer": "self-approved"}),
                apply=True,
            )
        self.assertEqual(self.manifest.read_bytes(), self.original_manifest)

    def test_invalid_media_symlink_hardlink_and_public_source_fail_closed(self) -> None:
        self.start()
        invalid = self.source("invalid.mp4", b"not an mp4")
        with self.assertRaisesRegex(session.SessionError, "container signature"):
            self.ingest_video(invalid)
        self.assertFalse(any((self.manifest.parent / "files").rglob("*.mp4")))

        real = self.source("real.mp4", self.video_bytes())
        linked = self.private / "linked.mp4"
        os.symlink(real, linked)
        with self.assertRaisesRegex(session.SessionError, "non-symlink"):
            self.ingest_video(linked)
        hard = self.private / "hard.mp4"
        os.link(real, hard)
        with self.assertRaisesRegex(session.SessionError, "hard link"):
            self.ingest_video(hard)

        public = self.root.parent / "outside.mp4"
        public.write_bytes(self.video_bytes())
        self.addCleanup(public.unlink, missing_ok=True)
        with self.assertRaisesRegex(session.SessionError, "private QA workspace"):
            self.ingest_video(public)

    def test_duplicate_non_save_bytes_and_destination_overwrite_are_rejected(self) -> None:
        self.start()
        self.ingest_video()
        duplicate = self.source("duplicate.mp4", self.video_bytes())
        with self.assertRaisesRegex(session.SessionError, "duplicate non-save"):
            session.ingest_artifact(
                inventory=self.inventory,
                manifest=self.manifest,
                source=duplicate,
                kind="video",
                label="independent second video",
                captured_at=CAPTURED_LOG,
                apply=True,
            )

        next_path = (
            self.manifest.parent / "files" / CASE_ID /
            f"{CASE_ID}-video-02.mp4"
        )
        next_path.write_bytes(b"owner bytes")
        with self.assertRaisesRegex(session.SessionError, "overwrite"):
            session.ingest_artifact(
                inventory=self.inventory,
                manifest=self.manifest,
                source=self.source("fresh.mp4", self.video_bytes(b"B")),
                kind="video",
                label="fresh second video",
                captured_at=CAPTURED_LOG,
                apply=True,
            )
        self.assertEqual(next_path.read_bytes(), b"owner bytes")

    def test_timestamp_and_selection_constraints_fail_before_mutation(self) -> None:
        with self.assertRaisesRegex(session.SessionError, "ROM selection"):
            session.start_case(
                inventory=self.inventory,
                manifest=self.manifest,
                case_id=CASE_ID,
                started_at=STARTED,
                rom_ids=["vertical-eeprom-rtc"],
                controller_ids=["pocket"],
                apply=True,
            )
        self.assertFalse((self.manifest.parent / session.SESSION_FILENAME).exists())
        self.start()
        with self.assertRaisesRegex(session.SessionError, "precedes"):
            session.ingest_artifact(
                inventory=self.inventory,
                manifest=self.manifest,
                source=self.source("early.txt", b"early\n"),
                kind="log",
                label="early",
                captured_at="2026-07-15T11:59:59Z",
                apply=True,
            )

    def test_manifest_or_inventory_change_blocks_active_session(self) -> None:
        self.start()
        document = json.loads(self.manifest.read_text())
        document["hardware_qa"]["operator"]["name"] = "tampered"
        self.manifest.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(session.SessionError, "manifest changed"):
            self.ingest_video()

    def test_concurrent_recorder_operation_fails_closed(self) -> None:
        with mock.patch.object(
            session.fcntl,
            "flock",
            side_effect=BlockingIOError("synthetic held workspace lock"),
        ):
            with self.assertRaisesRegex(session.SessionError, "operation is active"):
                self.start()
        self.assertFalse((self.manifest.parent / session.SESSION_FILENAME).exists())

    def test_atomic_manifest_failure_preserves_original_and_active_session(self) -> None:
        self.start()
        self.ingest_video()
        self.ingest_log()
        before = self.manifest.read_bytes()
        with mock.patch.object(
            session,
            "_atomic_replace",
            side_effect=OSError("synthetic atomic publication failure"),
        ):
            with self.assertRaisesRegex(OSError, "publication failure"):
                session.finish_case(
                    inventory=self.inventory,
                    manifest=self.manifest,
                    result=self.result(),
                    apply=True,
                )
        self.assertEqual(self.manifest.read_bytes(), before)
        self.assertTrue((self.manifest.parent / session.SESSION_FILENAME).exists())

    def test_recovery_clears_only_exact_published_prepared_sidecar(self) -> None:
        self.start()
        self.ingest_video()
        self.ingest_log()
        result = self.result()
        sidecar = self.manifest.parent / session.SESSION_FILENAME
        with mock.patch.object(
            session,
            "_unlink_exact",
            side_effect=OSError("synthetic post-publication cleanup failure"),
        ):
            with self.assertRaisesRegex(OSError, "cleanup failure"):
                session.finish_case(
                    inventory=self.inventory,
                    manifest=self.manifest,
                    result=result,
                    apply=True,
                )

        published = self.manifest.read_bytes()
        self.assertTrue(sidecar.is_file())
        active = json.loads(sidecar.read_text())["active_case"]
        self.assertEqual(
            active["prepared_finish"]["manifest_sha256"],
            hashlib.sha256(published).hexdigest(),
        )
        planned = session.recover_session(
            inventory=self.inventory, manifest=self.manifest, apply=False
        )
        self.assertTrue(planned["eligible"])
        self.assertEqual(self.manifest.read_bytes(), published)
        self.assertTrue(sidecar.exists())
        self.manifest.write_bytes(published + b"\n")
        with self.assertRaisesRegex(session.SessionError, "manifest changed"):
            session.recover_session(
                inventory=self.inventory, manifest=self.manifest, apply=True
            )
        self.assertTrue(sidecar.exists())
        self.manifest.write_bytes(published)
        applied = session.recover_session(
            inventory=self.inventory, manifest=self.manifest, apply=True
        )
        self.assertEqual(applied, planned)
        self.assertEqual(self.manifest.read_bytes(), published)
        self.assertFalse(sidecar.exists())

    def test_recovery_retains_active_unpublished_and_diverged_sessions(self) -> None:
        self.start()
        with self.assertRaisesRegex(session.SessionError, "no prepared finish"):
            session.recover_session(
                inventory=self.inventory, manifest=self.manifest, apply=True
            )

        self.ingest_video()
        self.ingest_log()
        result = self.result()
        original_replace = session._atomic_replace

        def fail_manifest_publication(path, payload, expected_sha256):
            if path.resolve() == self.manifest.resolve():
                raise OSError("synthetic manifest publication failure")
            return original_replace(path, payload, expected_sha256)

        with mock.patch.object(
            session, "_atomic_replace", side_effect=fail_manifest_publication
        ):
            with self.assertRaisesRegex(OSError, "publication failure"):
                session.finish_case(
                    inventory=self.inventory,
                    manifest=self.manifest,
                    result=result,
                    apply=True,
                )
        sidecar = self.manifest.parent / session.SESSION_FILENAME
        self.assertIsNotNone(
            json.loads(sidecar.read_text())["active_case"]["prepared_finish"]
        )
        with self.assertRaisesRegex(session.SessionError, "not published"):
            session.recover_session(
                inventory=self.inventory, manifest=self.manifest, apply=True
            )
        self.assertTrue(sidecar.exists())

        # The exact same human result resumes the prepared transaction.
        session.finish_case(
            inventory=self.inventory,
            manifest=self.manifest,
            result=result,
            apply=True,
        )
        self.assertFalse(sidecar.exists())

    def test_refuses_repo_and_non_private_workspace(self) -> None:
        original_mode = stat.S_IMODE(self.root.stat().st_mode)
        try:
            os.chmod(self.root, 0o755)
            with self.assertRaisesRegex(session.SessionError, "owner-only"):
                self.start()
        finally:
            os.chmod(self.root, original_mode)

        # A repository path is rejected before any JSON content can authorize it.
        with self.assertRaisesRegex(session.SessionError, "outside the repository"):
            session._private_workspace(
                session.ROOT / "hardware-qa-inventory.example.json",
                session.ROOT / "evidence" / "manifest.json",
            )


if __name__ == "__main__":
    unittest.main()
