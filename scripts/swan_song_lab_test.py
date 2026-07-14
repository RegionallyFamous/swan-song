#!/usr/bin/env python3
"""Offline contracts for the DigitalOcean Swan Song Lab control surface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import swan_song_lab as lab


class SwanSongLabTest(unittest.TestCase):
    def test_command_output_replaces_invalid_utf8_without_masking_status(self) -> None:
        command = [
            sys.executable,
            "-c",
            "import os; os.write(2, b'bad\\xfftail'); raise SystemExit(37)",
        ]
        result = lab.run(command, check=False)
        self.assertEqual(result.returncode, 37)
        self.assertEqual(result.stderr, "bad\ufffdtail")
        with self.assertRaisesRegex(lab.LabError, "bad\ufffdtail"):
            lab.run(command)

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

    def test_full_outbound_rules_use_current_digitalocean_api_sentinel(self) -> None:
        self.assertNotIn("ports:all", lab.OUTBOUND_RULES)
        self.assertEqual(lab.OUTBOUND_RULES.count("ports:0"), 3)
        self.assertIn("protocol:tcp,ports:0", lab.OUTBOUND_RULES)
        self.assertIn("protocol:udp,ports:0", lab.OUTBOUND_RULES)
        self.assertIn("protocol:icmp,ports:0", lab.OUTBOUND_RULES)

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
        self.assertIn("/srv/swan-song-data/containerd", script)
        self.assertIn("root = \"/srv/swan-song-data/containerd\"", script)
        self.assertIn("RequiresMountsFor=/srv/swan-song-data", script)
        self.assertIn("systemctl daemon-reload", script)
        self.assertIn("containerd.service", script)
        self.assertIn("git jq make perl python3 rsync tcl ufw", script)
        self.assertIn("systemctl enable --now containerd.service docker.service", script)
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
        self.assertIn("status=$?", remote)
        self.assertIn("trap - EXIT", remote)
        self.assertIn('(( status != 0 )) || status=1', remote)
        self.assertIn('exit "$status"', remote)
        self.assertIn(lab.ARCHIVE_SHA1, remote)
        self.assertIn("quartus_archive.py verify", remote)
        self.assertIn("QUARTUS_ACCEPT_EULA=1", remote)
        self.assertIn("quartus_docker.sh image", remote)
        self.assertIn("quartus-image-build.log", remote)
        self.assertIn('> "$build_log" 2>&1', remote)
        self.assertIn('tail -c 65536 "$build_log"', remote)
        self.assertIn('exit "$build_status"', remote)
        self.assertIn('rm -f "$build_log"', remote)
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

    def test_ssh_uses_bounded_keepalives_for_long_builds(self) -> None:
        state = {
            "public_ip": "192.0.2.10",
            "known_hosts_file": "/tmp/lab-known-hosts",
            "identity_file": "/tmp/lab-key",
        }
        command = lab.ssh_base(state)
        self.assertIn("ServerAliveInterval=30", command)
        self.assertIn("ServerAliveCountMax=3", command)

    def test_resume_reverifies_image_without_reuploading_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            commit = "a" * 40
            lab.save_state(path, {
                "magic": lab.MAGIC,
                "phase": "preparing-quartus",
                "repo": lab.DEFAULT_REPO,
                "default_branch": "main",
                "commit": commit,
                "public_ip": "192.0.2.10",
                "pending_resources": [],
            })
            args = argparse.Namespace(state=str(path), apply=True)
            with mock.patch.object(lab, "require_tools"):
                with mock.patch.object(
                    lab, "json_command", return_value={"commit": {"sha": commit}}
                ):
                    with mock.patch.object(
                        lab, "run", return_value=mock.Mock(returncode=0, stdout="", stderr="")
                    ) as command:
                        with mock.patch.object(lab, "install_runner") as install:
                            with mock.patch.object(lab, "register_runner") as register:
                                with mock.patch.object(lab, "wait_runner_online") as wait:
                                    with mock.patch("builtins.print"):
                                        lab.resume(args)
            remote = command.call_args.kwargs["input_text"]
            self.assertIn("quartus_docker.sh check-image", remote)
            self.assertNotIn(lab.ARCHIVE_NAME, remote)
            install.assert_called_once()
            register.assert_called_once()
            wait.assert_called_once()
            self.assertEqual(lab.load_state(path)["phase"], "ready")

    def test_warm_storage_moves_containerd_and_requires_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            lab.save_state(path, {
                "magic": lab.MAGIC,
                "public_ip": "192.0.2.10",
            })
            args = argparse.Namespace(state=str(path), apply=True)
            with mock.patch.object(
                lab, "run", return_value=mock.Mock(returncode=0, stdout="", stderr="")
            ) as command:
                with mock.patch("builtins.print"):
                    lab.warm_storage(args)
            remote = command.call_args.kwargs["input_text"]
            self.assertIn("rsync -aHAX --numeric-ids", remote)
            self.assertIn("root = \"/srv/swan-song-data/containerd\"", remote)
            self.assertIn("RequiresMountsFor=/srv/swan-song-data", remote)
            self.assertIn("refusing to replace an unowned containerd configuration", remote)
            self.assertIn("systemctl stop docker.service docker.socket containerd.service || true", remote)
            self.assertIn("containerd.service", remote)
            self.assertIn("mountpoint -q /srv/swan-song-data", remote)
            self.assertNotIn('test -z "$(find "$destination"', remote)
            self.assertIn("80 * 1024 * 1024", remote)
            self.assertIn(lab.IMAGE, remote)

    def test_rearm_reuses_image_updates_source_and_registers_one_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            old_commit = "a" * 40
            new_commit = "b" * 40
            lab.save_state(path, {
                "magic": lab.MAGIC,
                "phase": "dispatched",
                "repo": lab.DEFAULT_REPO,
                "default_branch": "main",
                "commit": old_commit,
                "public_ip": "192.0.2.10",
                "runner_id": 4,
                "workflow_run_id": 55,
                "workflow_run_url": "https://github.com/example/run/55",
                "resource_names": {
                    "runner": "old-runner",
                    "workflow_run": "swan-lab-old",
                },
                "pending_resources": [],
            })
            workflow = {
                "status": "completed",
                "conclusion": "failure",
                "head_sha": old_commit,
                "head_branch": "main",
                "event": "workflow_dispatch",
                "display_title": "Quartus fit candidate swan-lab-old",
            }
            args = argparse.Namespace(state=str(path), apply=True, ref="new-main")

            def record_runner(state: dict[str, object], unused_path: Path) -> None:
                state["runner_id"] = 99

            with mock.patch.object(lab, "require_tools"):
                with mock.patch.object(lab, "resource_get", side_effect=[workflow, None]):
                    with mock.patch.object(lab, "local_commit", return_value=new_commit) as local:
                        with mock.patch.object(
                            lab, "json_command", return_value={"commit": {"sha": new_commit}}
                        ):
                            with mock.patch.object(
                                lab, "run", return_value=mock.Mock(returncode=0, stdout="", stderr="")
                            ) as command:
                                with mock.patch.object(lab, "install_runner") as install:
                                    with mock.patch.object(lab, "register_runner", side_effect=record_runner) as register:
                                        with mock.patch.object(lab, "wait_runner_online") as wait:
                                            with mock.patch.object(lab.uuid, "uuid4", return_value=mock.Mock(hex="12345678")):
                                                with mock.patch("builtins.print"):
                                                    lab.rearm(args)
            local.assert_called_once_with("new-main")
            remote = command.call_args.kwargs["input_text"]
            self.assertIn(f"git fetch --depth=1 origin {new_commit}", remote)
            self.assertIn(f"git checkout --detach {new_commit}", remote)
            self.assertIn("quartus_docker.sh check-image", remote)
            self.assertNotIn(lab.ARCHIVE_NAME, remote)
            install.assert_called_once()
            register.assert_called_once()
            wait.assert_called_once()
            persisted = lab.load_state(path)
            self.assertEqual(persisted["phase"], "ready")
            self.assertEqual(persisted["commit"], new_commit)
            self.assertEqual(persisted["runner_id"], 99)
            self.assertEqual(persisted["runner_name"], "swan-rearm-bbbbbbbb-12345678")
            self.assertNotIn("workflow_run_id", persisted)
            self.assertEqual(persisted["completed_workflow_runs"][0]["id"], 55)

    def test_rearm_refuses_incomplete_run_or_existing_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            commit = "a" * 40
            state = {
                "magic": lab.MAGIC,
                "phase": "dispatched",
                "repo": lab.DEFAULT_REPO,
                "default_branch": "main",
                "commit": commit,
                "runner_id": 4,
                "workflow_run_id": 55,
                "resource_names": {},
                "pending_resources": [],
            }
            lab.save_state(path, state)
            args = argparse.Namespace(state=str(path), apply=True, ref=None)
            workflow = {
                "status": "in_progress",
                "head_sha": commit,
                "head_branch": "main",
                "event": "workflow_dispatch",
                "display_title": "Quartus fit candidate",
            }
            with mock.patch.object(lab, "require_tools"):
                with mock.patch.object(lab, "resource_get", return_value=workflow):
                    with self.assertRaisesRegex(lab.LabError, "not an exact completed run"):
                        lab.rearm(args)
            self.assertEqual(lab.load_state(path), state)
            workflow["status"] = "completed"
            with mock.patch.object(lab, "require_tools"):
                with mock.patch.object(lab, "resource_get", side_effect=[workflow, {"id": 4}]):
                    with mock.patch.object(
                        lab, "local_commit", side_effect=AssertionError("resolved a target with a live runner")
                    ):
                        with self.assertRaisesRegex(lab.LabError, "still exists"):
                            lab.rearm(args)
            self.assertEqual(lab.load_state(path), state)

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
                {
                    "id": 312570632,
                    "path": lab.regression_proof.WORKFLOW_PATH,
                    "state": "active",
                },
                {
                    "total_count": 1,
                    "workflow_runs": [
                        {
                            "id": 44,
                            "run_attempt": 1,
                            "workflow_id": 312570632,
                            "path": lab.regression_proof.WORKFLOW_PATH,
                            "head_sha": "a" * 40,
                            "head_branch": "main",
                            "event": "push",
                            "status": "completed",
                            "conclusion": "success",
                            "repository": {"full_name": lab.DEFAULT_REPO},
                        }
                    ]
                },
                {
                    "total_count": 1,
                    "jobs": [
                        {
                            "id": 45,
                            "run_id": 44,
                            "head_sha": "a" * 40,
                            "workflow_name": lab.regression_proof.WORKFLOW_NAME,
                            "name": lab.regression_proof.JOB_NAME,
                            "status": "completed",
                            "conclusion": "success",
                            "runner_group_name": "GitHub Actions",
                            "labels": ["ubuntu-24.04"],
                            "steps": [
                                {
                                    "name": name,
                                    "number": number,
                                    "status": "completed",
                                    "conclusion": "success",
                                }
                                for number, name in enumerate(
                                    lab.regression_proof.REQUIRED_STEPS,
                                    start=2,
                                )
                            ],
                        }
                    ],
                },
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
            self.assertEqual(persisted["hosted_regression_run_id"], 44)
            self.assertEqual(persisted["phase"], "dispatched")
            self.assertIn("actions/workflows/regression.yml", api.call_args_list[1].args[0][-1])
            self.assertIn("actions/workflows/312570632/runs?", api.call_args_list[2].args[0][-1])
            self.assertIn("actions/runs/44/attempts/1/jobs?", api.call_args_list[3].args[0][-1])
            for proof_call in api.call_args_list[1:4]:
                self.assertIn("X-GitHub-Api-Version: 2026-03-10", proof_call.args[0])
            payload = api.call_args_list[4].kwargs["input_body"]
            self.assertEqual(payload["ref"], "main")
            self.assertEqual(payload["inputs"]["lab_nonce"], "swan-lab-fixed")
            self.assertIs(payload["return_run_details"], True)

    def test_dispatch_refuses_without_exact_hosted_regression_before_mutation(self) -> None:
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
            responses = [
                {"commit": {"sha": "a" * 40}},
                {
                    "id": 312570632,
                    "path": lab.regression_proof.WORKFLOW_PATH,
                    "state": "active",
                },
                {"total_count": 0, "workflow_runs": []},
            ]
            with mock.patch.object(lab, "require_tools"):
                with mock.patch.object(lab, "json_command", side_effect=responses):
                    with mock.patch.object(
                        lab,
                        "resource_get",
                        side_effect=AssertionError("workflow was dispatched without proof"),
                    ):
                        with self.assertRaisesRegex(lab.LabError, "hosted regression proof failed"):
                            lab.dispatch(argparse.Namespace(state=str(path), apply=True))
            self.assertEqual(lab.load_state(path), state)

    def test_dispatch_adopts_exact_recorded_run_with_github_base_title(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            commit = "a" * 40
            lab.save_state(path, {
                "magic": lab.MAGIC,
                "name": "swan-song-quartus-lab",
                "phase": "ready",
                "repo": lab.DEFAULT_REPO,
                "commit": commit,
                "default_branch": "main",
                "runner_id": 4,
                "workflow_run_id": 55,
                "resource_names": {"workflow_run": "swan-lab-fixed"},
                "pending_resources": [],
            })
            workflow = {
                "head_sha": commit,
                "head_branch": "main",
                "event": "workflow_dispatch",
                "display_title": "Quartus fit candidate",
            }
            with mock.patch.object(lab, "resource_get", return_value=workflow):
                with mock.patch.object(
                    lab, "json_command", side_effect=AssertionError("dispatched twice")
                ):
                    with mock.patch("builtins.print"):
                        lab.dispatch(argparse.Namespace(state=str(path), apply=True))
            self.assertEqual(lab.load_state(path)["phase"], "dispatched")

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
