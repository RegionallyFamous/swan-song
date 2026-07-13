#!/usr/bin/env python3
"""Offline contracts for the DigitalOcean Swan Song Lab control surface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import swan_song_lab as lab


class SwanSongLabTest(unittest.TestCase):
    def launch_args(self, **changes: object) -> argparse.Namespace:
        values: dict[str, object] = {
            "apply": False,
            "accept_quartus_eula": False,
            "name": "swan-song-quartus-lab",
            "repo": lab.DEFAULT_REPO,
            "region": lab.DEFAULT_REGION,
            "size": lab.DEFAULT_SIZE,
            "image": lab.DEFAULT_IMAGE,
            "volume_gib": 200,
            "ssh_key": None,
            "identity_file": None,
            "ssh_cidr": None,
            "quartus_archive": None,
            "ref": None,
            "state": str(lab.DEFAULT_STATE),
        }
        values.update(changes)
        return argparse.Namespace(**values)

    @mock.patch.object(lab, "run", side_effect=AssertionError("dry-run executed a command"))
    def test_launch_is_non_mutating_dry_run_by_default(self, unused: mock.Mock) -> None:
        with mock.patch("builtins.print") as output:
            lab.launch(self.launch_args())
        rendered = "\n".join(str(call.args[0]) for call in output.call_args_list)
        self.assertIn("no cloud or network changes", rendered)
        self.assertIn("BILLING WARNING", rendered)
        self.assertIn("never uploaded", rendered)

    def test_apply_requires_key_cidr_archive_and_eula_before_network(self) -> None:
        args = self.launch_args(apply=True)
        with tempfile.TemporaryDirectory() as temporary:
            args.state = str(Path(temporary) / "state.json")
            with mock.patch.object(lab, "preflight_apply", side_effect=AssertionError("network preflight ran")):
                with self.assertRaisesRegex(lab.LabError, "requires --ssh-key"):
                    lab.launch(args)
        args.ssh_key = "123"
        args.ssh_cidr = "192.0.2.4/32"
        args.quartus_archive = "/tmp/Quartus-lite-21.1.1.850-linux.tar"
        with tempfile.TemporaryDirectory() as temporary:
            args.state = str(Path(temporary) / "state.json")
            with mock.patch.object(lab, "preflight_apply", side_effect=AssertionError("network preflight ran")):
                with self.assertRaisesRegex(lab.LabError, "accept-quartus-eula"):
                    lab.launch(args)

    def test_only_single_ipv4_address_can_reach_ssh(self) -> None:
        self.assertEqual(lab.validate_ssh_cidr("192.0.2.9/32"), "192.0.2.9/32")
        for invalid in ("0.0.0.0/0", "192.0.2.0/24", "2001:db8::1/128", "not-an-ip"):
            with self.subTest(invalid=invalid), self.assertRaises(lab.LabError):
                lab.validate_ssh_cidr(invalid)

    def test_cloud_init_is_secret_free_hardened_and_uses_volume(self) -> None:
        script = lab.cloud_init("swan-data", "192.0.2.9/32")
        self.assertIn("00-swan-song-lab.conf", script)
        self.assertIn("PasswordAuthentication no", script)
        self.assertIn("PermitRootLogin prohibit-password", script)
        self.assertIn("ufw default deny incoming", script)
        self.assertIn("allow from 192.0.2.9/32", script)
        self.assertIn("/dev/disk/by-id/scsi-0DO_Volume_swan-data", script)
        self.assertIn("refusing to format a volume that already has a filesystem signature", script)
        self.assertLess(script.index("if blkid"), script.index("mkfs.ext4"))
        self.assertIn("/srv/swan-song-data/docker", script)
        self.assertIn("systemctl enable --now docker", script)
        for forbidden in ("ghp_", "github_pat_", "encoded_jit_config", "DIGITALOCEAN_TOKEN", "DO_API_TOKEN"):
            self.assertNotIn(forbidden, script)

    def test_remote_prepare_verifies_then_deletes_archive_and_checks_image(self) -> None:
        state = {
            "public_ip": "192.0.2.10",
            "repo": lab.DEFAULT_REPO,
            "identity_file": "/tmp/lab-key",
            "known_hosts_file": "/tmp/lab-known-hosts",
        }
        archive = Path("/tmp") / lab.ARCHIVE_NAME
        commit = "a" * 40
        calls: list[tuple[list[str], str | None, int]] = []

        def fake_run(argv: list[str], *, input_text: str | None = None, timeout: int = 120, check: bool = True):
            calls.append((list(argv), input_text, timeout))
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(lab, "run", side_effect=fake_run):
            lab.prepare_remote(state, archive, commit)
        self.assertEqual(calls[0][0][0], "scp")
        self.assertIn("/tmp/lab-key", calls[0][0])
        remote = calls[1][1] or ""
        self.assertIn(f"trap cleanup EXIT", remote)
        self.assertIn(lab.ARCHIVE_SHA1, remote)
        self.assertIn("quartus_archive.py verify", remote)
        self.assertIn("QUARTUS_ACCEPT_EULA=1", remote)
        self.assertIn("quartus_docker.sh image", remote)
        self.assertIn("quartus_docker.sh check-image", remote)
        self.assertIn(lab.IMAGE, remote)
        self.assertEqual(calls[1][2], lab.BUILD_TIMEOUT)

    def test_jit_request_has_exact_workflow_labels_and_state_has_no_config(self) -> None:
        state = {
            "magic": lab.MAGIC,
            "repo": lab.DEFAULT_REPO,
            "public_ip": "192.0.2.10",
            "runner_name": "runner-name",
        }
        response = {"runner": {"id": 7}, "encoded_jit_config": "short-lived-secret"}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            with mock.patch.object(lab, "json_command", return_value=response) as request:
                with mock.patch.object(lab, "run", return_value=mock.Mock(returncode=0, stdout="", stderr="")) as remote:
                    lab.register_runner(state, path)
            body = request.call_args.kwargs["input_body"]
            self.assertEqual(body["labels"], lab.LABELS)
            self.assertNotIn("short-lived-secret", path.read_text())
            self.assertIn("--jitconfig", remote.call_args.kwargs["input_text"])

    def test_destroy_is_preview_only_without_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            lab.save_state(path, {
                "magic": lab.MAGIC,
                "name": "swan-song-quartus-lab",
                "runner_id": 1,
                "droplet_id": 2,
                "volume_id": "volume",
                "firewall_id": "firewall",
                "tag": "tag",
            })
            args = argparse.Namespace(state=str(path), apply=False, confirm=None)
            with mock.patch.object(lab, "run", side_effect=AssertionError("destroy preview mutated state")):
                with mock.patch("builtins.print"):
                    lab.destroy(args)
            self.assertTrue(path.exists())

    def test_resource_get_does_not_add_doctl_flag_to_gh(self) -> None:
        responses = [
            mock.Mock(returncode=0, stdout='{"id": 7}', stderr=""),
            mock.Mock(returncode=0, stdout='[{"id": 8}]', stderr=""),
        ]
        with mock.patch.object(lab, "run", side_effect=responses) as command:
            self.assertEqual(lab.resource_get(["gh", "api", "repos/o/r/actions/runners/7"])["id"], 7)
            self.assertEqual(lab.resource_get(["doctl", "compute", "droplet", "get", "8"])["id"], 8)
        self.assertNotIn("--output", command.call_args_list[0].args[0])
        self.assertEqual(command.call_args_list[1].args[0][-2:], ["--output", "json"])

    def test_resource_get_only_treats_explicit_not_found_as_absent(self) -> None:
        not_found = mock.Mock(returncode=1, stdout="", stderr="HTTP 404: not found")
        unauthorized = mock.Mock(returncode=1, stdout="", stderr="HTTP 401: bad credentials")
        server_error = mock.Mock(returncode=1, stdout="", stderr="HTTP 500: retry")
        malformed = mock.Mock(returncode=0, stdout="not json", stderr="")
        with mock.patch.object(lab, "run", side_effect=[not_found, unauthorized, server_error, malformed]):
            self.assertIsNone(lab.resource_get(["gh", "api", "repos/o/r/actions/runners/7"]))
            with self.assertRaisesRegex(lab.LabError, "absence is unconfirmed"):
                lab.resource_get(["gh", "api", "repos/o/r/actions/runners/7"])
            with self.assertRaisesRegex(lab.LabError, "absence is unconfirmed"):
                lab.resource_get(["gh", "api", "repos/o/r/actions/runners/7"])
            with self.assertRaisesRegex(lab.LabError, "invalid JSON"):
                lab.resource_get(["gh", "api", "repos/o/r/actions/runners/7"])

    def test_resource_id_404_does_not_mask_401_status(self) -> None:
        unauthorized = mock.Mock(
            returncode=1,
            stdout="",
            stderr='GET https://api.digitalocean.com/v2/droplets/404: 401 (request "abc") unauthorized',
        )
        with mock.patch.object(lab, "run", return_value=unauthorized):
            with self.assertRaisesRegex(lab.LabError, "absence is unconfirmed"):
                lab.resource_get(["doctl", "compute", "droplet", "get", "404"])

    def test_destroy_preserves_state_when_absence_is_unconfirmed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            lab.save_state(path, {
                "magic": lab.MAGIC,
                "name": "swan-song-quartus-lab",
                "repo": lab.DEFAULT_REPO,
                "runner_id": 1,
                "pending_resources": [],
            })
            args = argparse.Namespace(state=str(path), apply=True, confirm="swan-song-quartus-lab")
            with mock.patch.object(lab, "require_tools"):
                with mock.patch.object(lab, "recover_pending"):
                    with mock.patch.object(lab, "cancel_workflow_run"):
                        with mock.patch.object(lab, "resource_get", side_effect=lab.LabError("network uncertain")):
                            with self.assertRaisesRegex(lab.LabError, "network uncertain"):
                                lab.destroy(args)
            self.assertTrue(path.exists())

    def test_ssh_strips_argparse_separator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            lab.save_state(path, {"magic": lab.MAGIC, "public_ip": "192.0.2.10"})
            args = argparse.Namespace(state=str(path), command=["--", "docker", "info"])
            with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)) as command:
                lab.ssh_command(args)
            self.assertEqual(command.call_args.args[0][-2:], ["docker", "info"])
            self.assertNotEqual(command.call_args.args[0][-3], "--")

    def test_uncertain_volume_create_is_reconciled_by_exact_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            state = {
                "magic": lab.MAGIC,
                "resource_names": {"volume": "exact-volume"},
                "pending_resources": ["volume"],
            }
            lab.save_state(path, state)
            with mock.patch.object(lab, "object_list", return_value=[{"name": "exact-volume", "id": "volume-id"}]):
                lab.recover_pending(state, path)
            self.assertEqual(state["volume_id"], "volume-id")
            self.assertEqual(state["pending_resources"], [])

    def test_eventual_consistency_miss_keeps_pending_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            state = {
                "magic": lab.MAGIC,
                "resource_names": {"volume": "exact-volume"},
                "pending_resources": ["volume"],
            }
            lab.save_state(path, state)
            with mock.patch.object(lab, "object_list", return_value=[]):
                with self.assertRaisesRegex(lab.LabError, "not visible yet"):
                    lab.recover_pending(state, path)
            self.assertEqual(lab.load_state(path)["pending_resources"], ["volume"])

    def test_delete_requires_post_delete_confirmed_absence(self) -> None:
        errors: list[str] = []
        with mock.patch.object(lab, "resource_get", side_effect=[{"id": 7}, None]) as lookup:
            with mock.patch.object(lab, "run", return_value=mock.Mock(returncode=0, stdout="", stderr="")):
                lab.delete_and_confirm(["get"], ["delete"], errors, "runner")
        self.assertEqual(errors, [])
        self.assertEqual(lookup.call_count, 2)

    def test_cancel_waits_until_recorded_run_is_stopped(self) -> None:
        state = {"repo": lab.DEFAULT_REPO, "workflow_run_id": 99}
        statuses = [{"status": "queued"}, {"status": "in_progress"}, {"status": "completed"}]
        with mock.patch.object(lab, "resource_get", side_effect=statuses):
            with mock.patch.object(lab, "run", return_value=mock.Mock(returncode=0, stdout="", stderr="")) as cancel:
                with mock.patch.object(lab.time, "sleep"):
                    lab.cancel_workflow_run(state)
        self.assertIn("repos/RegionallyFamous/swan-song/actions/runs/99/cancel", cancel.call_args.args[0])

    def test_dispatch_records_exact_api_run_and_commit_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            state = {
                "magic": lab.MAGIC,
                "name": "swan-song-quartus-lab",
                "phase": "ready",
                "repo": lab.DEFAULT_REPO,
                "commit": "a" * 40,
                "default_branch": "main",
                "runner_id": 4,
                "resource_names": {},
                "pending_resources": [],
            }
            lab.save_state(path, state)
            args = argparse.Namespace(state=str(path), apply=True)
            responses = [
                {"commit": {"sha": "a" * 40}},
                {"workflow_run_id": 55, "html_url": "https://github.com/example/run/55"},
            ]
            workflow = {
                "head_sha": "a" * 40,
                "head_branch": "main",
                "event": "workflow_dispatch",
                "display_title": "Quartus fit candidate swan-lab-fixed",
            }
            with mock.patch.object(lab, "require_tools"):
                with mock.patch.object(lab.uuid, "uuid4", return_value=mock.Mock(hex="fixed")):
                    with mock.patch.object(lab, "json_command", side_effect=responses) as api:
                        with mock.patch.object(lab, "resource_get", return_value=workflow):
                            with mock.patch("builtins.print"):
                                lab.dispatch(args)
            persisted = lab.load_state(path)
            self.assertEqual(persisted["workflow_run_id"], 55)
            self.assertEqual(persisted["phase"], "dispatched")
            payload = api.call_args_list[1].kwargs["input_body"]
            self.assertEqual(payload["ref"], "main")
            self.assertEqual(payload["inputs"]["lab_nonce"], "swan-lab-fixed")

    def test_state_file_is_private_and_rejects_wrong_magic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            lab.save_state(path, {"magic": lab.MAGIC, "name": "test"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(lab.load_state(path)["name"], "test")
            path.write_text(json.dumps({"magic": "wrong"}))
            with self.assertRaises(lab.LabError):
                lab.load_state(path)


if __name__ == "__main__":
    unittest.main()
