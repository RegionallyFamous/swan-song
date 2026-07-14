#!/usr/bin/env python3
"""Fail-closed tests for the hosted regression proof."""

from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
import tempfile
from unittest import mock
import unittest
from urllib import parse

import verify_hosted_regression as proof


REPOSITORY = "RegionallyFamous/swan-song"
SHA = "a" * 40
BRANCH = "main"
WORKFLOW_ID = 312570632


def metadata(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "id": WORKFLOW_ID,
        "path": proof.WORKFLOW_PATH,
        "state": "active",
    }
    body.update(changes)
    return body


def run_body(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "id": 29295712712,
        "run_attempt": 1,
        "workflow_id": WORKFLOW_ID,
        "path": proof.WORKFLOW_PATH,
        "head_sha": SHA,
        "head_branch": BRANCH,
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": REPOSITORY},
    }
    body.update(changes)
    return body


def job_body(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "id": 86968627678,
        "run_id": 29295712712,
        "head_sha": SHA,
        "workflow_name": proof.WORKFLOW_NAME,
        "name": proof.JOB_NAME,
        "status": "completed",
        "conclusion": "success",
        "runner_group_name": "GitHub Actions",
        "labels": ["ubuntu-24.04"],
        "steps": [
            {"name": "Set up job", "number": 1, "status": "completed", "conclusion": "success"},
            *[
                {
                    "name": name,
                    "number": number,
                    "status": "completed",
                    "conclusion": "success",
                }
                for number, name in enumerate(proof.REQUIRED_STEPS, start=2)
            ],
            {"name": "Complete job", "number": 9, "status": "completed", "conclusion": "success"},
        ],
    }
    body.update(changes)
    return body


class HostedRegressionProofTest(unittest.TestCase):
    def test_checked_out_regression_workflow_source_is_locked(self) -> None:
        proof.verify_regression_workflow_source()
        source = proof.DEFAULT_WORKFLOW_SOURCE.read_text(encoding="utf-8")
        mutations = (
            source.replace("        run: make regression\n", "        run: true\n"),
            source.replace(
                "          .github/toolchain/verify.sh\n",
                "          .github/toolchain/verify.sh || true\n",
            ),
            source.replace(
                "  verilator:\n    runs-on: ubuntu-24.04\n",
                "  verilator:\n    runs-on: ubuntu-24.04\n    if: false\n",
            ),
            source.replace(
                "      - name: Verify immutable HDL toolchain\n",
                "__STEP_SENTINEL__\n",
            ).replace(
                "      - name: Run open-ROM framebuffer regressions\n",
                "      - name: Verify immutable HDL toolchain\n",
            ).replace(
                "__STEP_SENTINEL__\n",
                "      - name: Run open-ROM framebuffer regressions\n",
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "regression.yml"
            for mutation in mutations:
                path.write_text(mutation, encoding="utf-8")
                with self.assertRaises(proof.ProofError):
                    proof.verify_regression_workflow_source(path)
            target = Path(temporary) / "target.yml"
            target.write_text(source, encoding="utf-8")
            path.unlink()
            path.symlink_to(target)
            with self.assertRaisesRegex(proof.ProofError, "not a regular file"):
                proof.verify_regression_workflow_source(path)

    def test_transport_uses_official_version_and_bearer_token_headers(self) -> None:
        class Response:
            status = 200

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *unused: object) -> None:
                return None

            def read(self, unused_limit: int) -> bytes:
                return b'{"id": 7}'

        with mock.patch.object(proof.request, "urlopen", return_value=Response()) as urlopen:
            self.assertEqual(proof.fetch_json("repos/o/r/actions/workflows/x", "secret"), {"id": 7})
        api_request = urlopen.call_args.args[0]
        self.assertEqual(api_request.get_header("X-github-api-version"), proof.API_VERSION)
        self.assertEqual(api_request.get_header("Authorization"), "Bearer secret")
        self.assertEqual(api_request.get_header("Accept"), "application/vnd.github+json")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 30)

        with mock.patch.object(
            proof.request,
            "urlopen",
            side_effect=AssertionError("network used without a token"),
        ):
            with self.assertRaisesRegex(proof.ProofError, "GITHUB_TOKEN is required"):
                proof.fetch_json("repos/o/r/actions/workflows/x", "")

    def test_workflow_metadata_binds_active_path_and_id(self) -> None:
        self.assertEqual(proof.verify_workflow_metadata(metadata()), WORKFLOW_ID)
        for mutation in (
            metadata(id=True),
            metadata(id=0),
            metadata(path=".github/workflows/other.yml"),
            metadata(state="disabled_manually"),
            [],
        ):
            with self.subTest(mutation=mutation), self.assertRaises(proof.ProofError):
                proof.verify_workflow_metadata(mutation)

    def test_run_must_match_every_exact_commit_contract(self) -> None:
        valid = {"total_count": 1, "workflow_runs": [run_body()]}
        accepted = proof.verify_workflow_runs(
            valid,
            repository=REPOSITORY,
            workflow_id=WORKFLOW_ID,
            sha=SHA,
            branch=BRANCH,
        )
        self.assertEqual(accepted["id"], 29295712712)

        mutations = {
            "workflow_id": WORKFLOW_ID + 1,
            "path": ".github/workflows/other.yml",
            "head_sha": "b" * 40,
            "head_branch": "feature",
            "event": "pull_request",
            "status": "in_progress",
            "conclusion": "failure",
            "repository": {"full_name": "Other/repository"},
            "id": True,
        }
        for field, value in mutations.items():
            with self.subTest(field=field), self.assertRaises(proof.ProofError):
                proof.verify_workflow_runs(
                    {"total_count": 1, "workflow_runs": [run_body(**{field: value})]},
                    repository=REPOSITORY,
                    workflow_id=WORKFLOW_ID,
                    sha=SHA,
                    branch=BRANCH,
                )

    def test_no_success_or_malformed_response_fails_closed(self) -> None:
        for body in (
            {"total_count": 0, "workflow_runs": []},
            {"total_count": 1, "workflow_runs": [None]},
            {"total_count": 1, "workflow_runs": "not-a-list"},
            {"total_count": 2, "workflow_runs": [run_body()]},
            [],
        ):
            with self.subTest(body=body), self.assertRaises(proof.ProofError):
                proof.verify_workflow_runs(
                    body,
                    repository=REPOSITORY,
                    workflow_id=WORKFLOW_ID,
                    sha=SHA,
                    branch=BRANCH,
                )

    def test_job_must_be_hosted_and_run_every_required_step_successfully(self) -> None:
        valid = {"total_count": 1, "jobs": [job_body()]}
        accepted = proof.verify_workflow_jobs(valid, run_id=29295712712, sha=SHA)
        self.assertEqual(accepted["id"], 86968627678)

        mutations = {
            "run_id": 7,
            "head_sha": "b" * 40,
            "workflow_name": "Other workflow",
            "name": "other-job",
            "status": "in_progress",
            "conclusion": "skipped",
            "runner_group_name": "Self-hosted",
            "labels": ["self-hosted"],
            "id": True,
        }
        for field, value in mutations.items():
            with self.subTest(field=field), self.assertRaises(proof.ProofError):
                proof.verify_workflow_jobs(
                    {"total_count": 1, "jobs": [job_body(**{field: value})]},
                    run_id=29295712712,
                    sha=SHA,
                )

        steps = list(job_body()["steps"])
        regression_step = next(
            step
            for step in steps
            if step["name"] == "Run open-ROM framebuffer regressions"
        )
        regression_step["conclusion"] = "skipped"
        with self.assertRaisesRegex(proof.ProofError, "did not complete successfully"):
            proof.verify_workflow_jobs(
                {"total_count": 1, "jobs": [job_body(steps=steps)]},
                run_id=29295712712,
                sha=SHA,
            )

        missing = [
            step
            for step in job_body()["steps"]
            if step["name"] != "Verify immutable HDL toolchain"
        ]
        with self.assertRaisesRegex(proof.ProofError, "does not contain exactly one"):
            proof.verify_workflow_jobs(
                {"total_count": 1, "jobs": [job_body(steps=missing)]},
                run_id=29295712712,
                sha=SHA,
            )

    def test_query_uses_workflow_id_and_exact_server_side_filters(self) -> None:
        endpoint = proof.workflow_runs_endpoint(REPOSITORY, WORKFLOW_ID, SHA, BRANCH)
        path, encoded = endpoint.split("?", 1)
        self.assertEqual(
            path,
            f"repos/{REPOSITORY}/actions/workflows/{WORKFLOW_ID}/runs",
        )
        self.assertEqual(
            parse.parse_qs(encoded),
            {
                "branch": [BRANCH],
                "event": ["push"],
                "head_sha": [SHA],
                "status": ["success"],
                "per_page": ["100"],
            },
        )
        self.assertEqual(
            proof.workflow_jobs_endpoint(REPOSITORY, 29295712712, 1),
            f"repos/{REPOSITORY}/actions/runs/29295712712/attempts/1/jobs?per_page=100",
        )

    def test_cli_fetches_metadata_then_runs_and_never_accepts_empty_result(self) -> None:
        environment = {
            "GITHUB_TOKEN": "test-token",
            "GITHUB_REPOSITORY": REPOSITORY,
            "GITHUB_SHA": SHA,
            "GITHUB_REF_NAME": BRANCH,
        }
        output = io.StringIO()
        with mock.patch.dict(os.environ, environment, clear=True):
            with mock.patch.object(
                proof,
                "fetch_json",
                side_effect=[
                    metadata(),
                    {"total_count": 1, "workflow_runs": [run_body()]},
                    {"total_count": 1, "jobs": [job_body()]},
                ],
            ) as fetch:
                with contextlib.redirect_stdout(output):
                    self.assertEqual(proof.main([]), 0)
        self.assertIn("PASS exact-commit hosted regression", output.getvalue())
        self.assertEqual(fetch.call_args_list[0].args[1], "test-token")
        self.assertIn(f"actions/workflows/{WORKFLOW_ID}/runs?", fetch.call_args_list[1].args[0])
        self.assertIn("actions/runs/29295712712/attempts/1/jobs?", fetch.call_args_list[2].args[0])

        error_output = io.StringIO()
        with mock.patch.dict(os.environ, environment, clear=True):
            with mock.patch.object(
                proof,
                "fetch_json",
                side_effect=[metadata(), {"total_count": 0, "workflow_runs": []}],
            ):
                with contextlib.redirect_stderr(error_output):
                    self.assertEqual(proof.main([]), 1)
        self.assertIn("no completed successful hosted regression", error_output.getvalue())


if __name__ == "__main__":
    unittest.main()
