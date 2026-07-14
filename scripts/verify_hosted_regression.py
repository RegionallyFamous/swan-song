#!/usr/bin/env python3
"""Prove that the exact default-branch commit passed the hosted regression."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Mapping, Sequence
from urllib import error, parse, request


API_ROOT = "https://api.github.com"
API_VERSION = "2026-03-10"
WORKFLOW_FILENAME = "regression.yml"
WORKFLOW_PATH = ".github/workflows/regression.yml"
WORKFLOW_NAME = "FPGA regression"
JOB_NAME = "verilator"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKFLOW_SOURCE = ROOT / WORKFLOW_PATH
CHECKOUT_USE = (
    "uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0"
)
REQUIRED_STEPS = (
    "Check out source",
    "Verify immutable HDL toolchain",
    "Run open-ROM framebuffer regressions",
)
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class ProofError(ValueError):
    """The GitHub response does not prove the required regression result."""


def verify_regression_workflow_source(path: Path = DEFAULT_WORKFLOW_SOURCE) -> None:
    """Lock the checked-out hosted lane to the commands whose steps are proven."""
    try:
        file_stat = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(file_stat.st_mode):
            raise ProofError("hosted regression workflow source is not a regular file")
        if file_stat.st_size > 256 * 1024:
            raise ProofError("hosted regression workflow source exceeds the size limit")
        source = path.read_text(encoding="utf-8")
    except ProofError:
        raise
    except (OSError, UnicodeError) as exc:
        raise ProofError(f"could not read hosted regression workflow source: {exc}") from exc
    required_fragments = (
        "name: FPGA regression\n",
        "permissions:\n  contents: read\n",
        "jobs:\n  verilator:\n    runs-on: ubuntu-24.04\n",
        "    timeout-minutes: 30\n",
        "      - name: Check out source\n"
        f"        {CHECKOUT_USE}\n",
        "      - name: Verify immutable HDL toolchain\n"
        "        run: |\n"
        "          echo \"$GITHUB_WORKSPACE/.github/toolchain\" >> \"$GITHUB_PATH\"\n"
        "          .github/toolchain/verify.sh\n"
        "      - name: Run open-ROM framebuffer regressions\n"
        "        run: make regression\n",
    )
    for fragment in required_fragments:
        if source.count(fragment) != 1:
            raise ProofError(f"hosted regression workflow source contract changed: {fragment.strip()}")
    if "    if:" in source:
        raise ProofError("hosted regression workflow must not conditionally skip its job")
    required_names = [f"      - name: {name}\n" for name in REQUIRED_STEPS]
    positions = [source.index(name) for name in required_names]
    if positions != sorted(positions):
        raise ProofError("hosted regression workflow source steps are out of order")


def validate_repository(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise ProofError("repository must be OWNER/REPO")
    return value


def validate_sha(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ProofError("commit must be a full lowercase 40-hex SHA")
    return value


def validate_branch(value: str) -> str:
    if (
        not value
        or len(value) > 255
        or not re.fullmatch(r"[A-Za-z0-9._/-]+", value)
        or value.startswith("/")
        or value.endswith("/")
        or ".." in value
        or "//" in value
    ):
        raise ProofError("default branch has an unsupported name")
    return value


def workflow_endpoint(repository: str) -> str:
    repository = validate_repository(repository)
    return f"repos/{repository}/actions/workflows/{WORKFLOW_FILENAME}"


def workflow_runs_endpoint(repository: str, workflow_id: int, sha: str, branch: str) -> str:
    repository = validate_repository(repository)
    sha = validate_sha(sha)
    branch = validate_branch(branch)
    if isinstance(workflow_id, bool) or not isinstance(workflow_id, int) or workflow_id <= 0:
        raise ProofError("workflow ID must be a positive integer")
    query = parse.urlencode(
        {
            "branch": branch,
            "event": "push",
            "head_sha": sha,
            "status": "success",
            "per_page": "100",
        }
    )
    return f"repos/{repository}/actions/workflows/{workflow_id}/runs?{query}"


def workflow_jobs_endpoint(repository: str, run_id: int, run_attempt: int) -> str:
    repository = validate_repository(repository)
    for value, label in ((run_id, "run ID"), (run_attempt, "run attempt")):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ProofError(f"{label} must be a positive integer")
    return (
        f"repos/{repository}/actions/runs/{run_id}/attempts/{run_attempt}/jobs"
        "?per_page=100"
    )


def verify_workflow_metadata(payload: Any) -> int:
    if not isinstance(payload, dict):
        raise ProofError("workflow metadata is not an object")
    workflow_id = payload.get("id")
    if isinstance(workflow_id, bool) or not isinstance(workflow_id, int) or workflow_id <= 0:
        raise ProofError("workflow metadata has no positive integer ID")
    if payload.get("path") != WORKFLOW_PATH:
        raise ProofError(f"workflow path is not exactly {WORKFLOW_PATH}")
    if payload.get("state") != "active":
        raise ProofError("hosted regression workflow is not active")
    return workflow_id


def verify_workflow_runs(
    payload: Any,
    *,
    repository: str,
    workflow_id: int,
    sha: str,
    branch: str,
) -> Mapping[str, Any]:
    repository = validate_repository(repository)
    sha = validate_sha(sha)
    branch = validate_branch(branch)
    if isinstance(workflow_id, bool) or not isinstance(workflow_id, int) or workflow_id <= 0:
        raise ProofError("workflow ID must be a positive integer")
    if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs"), list):
        raise ProofError("workflow-run response is malformed")

    runs = payload["workflow_runs"]
    total_count = payload.get("total_count")
    if (
        isinstance(total_count, bool)
        or not isinstance(total_count, int)
        or total_count != len(runs)
    ):
        raise ProofError("workflow-run response has an inconsistent result count")
    if not runs:
        raise ProofError(
            "no completed successful hosted regression exists for the exact default-branch commit"
        )
    validated: list[Mapping[str, Any]] = []
    for run in runs:
        if not isinstance(run, dict):
            raise ProofError("workflow-run response contains a non-object run")
        run_id = run.get("id")
        run_attempt = run.get("run_attempt")
        repository_body = run.get("repository")
        actual_repository = (
            repository_body.get("full_name") if isinstance(repository_body, dict) else None
        )
        expected = {
            "workflow_id": workflow_id,
            "path": WORKFLOW_PATH,
            "head_sha": sha,
            "head_branch": branch,
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        }
        if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
            raise ProofError("workflow-run response has no positive integer run ID")
        if (
            isinstance(run_attempt, bool)
            or not isinstance(run_attempt, int)
            or run_attempt <= 0
        ):
            raise ProofError("workflow-run response has no positive integer run attempt")
        if actual_repository != repository:
            raise ProofError("workflow run is not bound to the expected repository")
        for field, value in expected.items():
            if run.get(field) != value:
                raise ProofError(f"workflow run is not bound to expected {field}={value}")
        validated.append(run)

    # Re-runs or a repeated push of the same commit can legitimately return more
    # than one fully bound success. Prefer the newest immutable run ID.
    return max(validated, key=lambda item: int(item["id"]))


def verify_workflow_jobs(payload: Any, *, run_id: int, sha: str) -> Mapping[str, Any]:
    sha = validate_sha(sha)
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
        raise ProofError("run ID must be a positive integer")
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ProofError("workflow-job response is malformed")
    jobs = payload["jobs"]
    total_count = payload.get("total_count")
    if (
        isinstance(total_count, bool)
        or not isinstance(total_count, int)
        or total_count != len(jobs)
        or total_count != 1
    ):
        raise ProofError("hosted regression must contain exactly one workflow job")
    job = jobs[0]
    if not isinstance(job, dict):
        raise ProofError("workflow-job response contains a non-object job")
    job_id = job.get("id")
    expected = {
        "run_id": run_id,
        "head_sha": sha,
        "workflow_name": WORKFLOW_NAME,
        "name": JOB_NAME,
        "status": "completed",
        "conclusion": "success",
        "runner_group_name": "GitHub Actions",
    }
    if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id <= 0:
        raise ProofError("workflow job has no positive integer job ID")
    for field, value in expected.items():
        if job.get(field) != value:
            raise ProofError(f"workflow job is not bound to expected {field}={value}")
    labels = job.get("labels")
    if not isinstance(labels, list) or "ubuntu-24.04" not in labels:
        raise ProofError("regression job did not run on the required GitHub-hosted Ubuntu image")
    steps = job.get("steps")
    if not isinstance(steps, list):
        raise ProofError("workflow job has no step evidence")
    required_numbers: list[int] = []
    for required_name in REQUIRED_STEPS:
        matches = [step for step in steps if isinstance(step, dict) and step.get("name") == required_name]
        if len(matches) != 1:
            raise ProofError(f"workflow job does not contain exactly one {required_name} step")
        step = matches[0]
        number = step.get("number")
        if (
            isinstance(number, bool)
            or not isinstance(number, int)
            or step.get("status") != "completed"
            or step.get("conclusion") != "success"
        ):
            raise ProofError(f"workflow step did not complete successfully: {required_name}")
        required_numbers.append(number)
    if required_numbers != sorted(required_numbers) or len(set(required_numbers)) != len(required_numbers):
        raise ProofError("required hosted regression steps ran out of order")
    return job


def fetch_json(endpoint: str, token: str) -> Any:
    if not token:
        raise ProofError("GITHUB_TOKEN is required to verify the hosted regression")
    url = f"{API_ROOT}/{endpoint.lstrip('/')}"
    api_request = request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "swan-song-hosted-regression-proof",
            "X-GitHub-Api-Version": API_VERSION,
        },
        method="GET",
    )
    try:
        with request.urlopen(api_request, timeout=30) as response:
            if response.status != 200:
                raise ProofError(f"GitHub API returned HTTP {response.status}")
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except (error.HTTPError, error.URLError, TimeoutError, OSError) as exc:
        raise ProofError(f"GitHub API request failed: {exc}") from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise ProofError("GitHub API response exceeded the size limit")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProofError("GitHub API returned invalid JSON") from exc


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    result.add_argument("--sha", default=os.environ.get("GITHUB_SHA"))
    result.add_argument("--branch", default=os.environ.get("GITHUB_REF_NAME"))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        repository = validate_repository(args.repository or "")
        sha = validate_sha(args.sha or "")
        branch = validate_branch(args.branch or "")
        verify_regression_workflow_source()
        token = os.environ.get("GITHUB_TOKEN", "")
        metadata = fetch_json(workflow_endpoint(repository), token)
        workflow_id = verify_workflow_metadata(metadata)
        runs = fetch_json(
            workflow_runs_endpoint(repository, workflow_id, sha, branch),
            token,
        )
        proven = verify_workflow_runs(
            runs,
            repository=repository,
            workflow_id=workflow_id,
            sha=sha,
            branch=branch,
        )
        jobs = fetch_json(
            workflow_jobs_endpoint(repository, int(proven["id"]), int(proven["run_attempt"])),
            token,
        )
        job = verify_workflow_jobs(jobs, run_id=int(proven["id"]), sha=sha)
    except ProofError as exc:
        print(f"verify_hosted_regression.py: {exc}", file=sys.stderr)
        return 1
    print(
        "PASS exact-commit hosted regression "
        f"workflow={workflow_id} run={proven['id']} job={job['id']} source={repository}@{sha}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
