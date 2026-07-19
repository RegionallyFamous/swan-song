#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Regionally Famous contributors
"""Create the deterministic, source-inclusive Dialbug public release."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
RELEASE_VERSION = "0.1.0"
LICENSE_ID = "GPL-3.0-or-later"
NAME = f"dialbug-{RELEASE_VERSION}"
ROM_SOURCE = ROOT / "dialbug.wsc"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def package_files() -> list[Path]:
    files = [
        ROOT / "dialbug.wsc",
        ROOT / "README.md",
        ROOT / "CREDITS.md",
        ROOT / "COPYING",
        ROOT / "THIRD_PARTY_NOTICES.md",
        ROOT / "Makefile",
        ROOT / "wfconfig.toml",
        ROOT / "scripts" / "verify_release.py",
        ROOT / "scripts" / "package_release.py",
        ROOT / "scripts" / "build_interface_art.py",
        ROOT / "scripts" / "normalize_wfprocess_c.py",
        ROOT / "release" / "RELEASE_NOTES.md",
        ROOT / "release" / "HARDWARE_TEST.md",
        ROOT / "release" / "LICENSE_STATUS.md",
        ROOT / "release" / "verification-report.json",
        ROOT / "release" / "playtest-plan.json",
        ROOT / "release" / "swansong-playtest-report.json",
        ROOT / "release" / "swansong-final-frame.png",
        ROOT / "release" / "battery-glow-mednafen-proof.wav",
    ]
    files.extend(sorted((ROOT / "src").glob("*.[ch]")))
    files.extend(sorted(path for path in (ROOT / "assets").rglob("*") if path.is_file()))
    files.extend(sorted(path for path in (ROOT / "music").rglob("*") if path.is_file()))
    files.extend(sorted((ROOT / "release" / "plans").glob("*.json")))
    files.extend(sorted((ROOT / "release" / "tracks").glob("*")))
    missing = [path for path in files if not path.is_file()]
    if missing:
        raise SystemExit("missing release inputs: " + ", ".join(map(str, missing)))
    return sorted(set(files), key=lambda path: path.relative_to(ROOT).as_posix())


def main() -> int:
    verification = json.loads(
        (ROOT / "release" / "verification-report.json").read_text(encoding="utf-8")
    )
    if verification.get("status") != "pass":
        raise SystemExit("verification-report.json does not pass")
    current_rom_hash = sha256_file(ROM_SOURCE)
    if current_rom_hash != verification.get("rom", {}).get("sha256"):
        raise SystemExit("ROM changed after release verification")

    files = package_files()
    manifest = {
        "schema": "dialbug-package-manifest-v1",
        "release": RELEASE_VERSION,
        "license": LICENSE_ID,
        "publicDistributionAuthorized": True,
        "correspondingSourceIncluded": True,
        "files": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "byteCount": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in files
        ],
    }
    manifest_data = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()

    DIST.mkdir(parents=True, exist_ok=True)
    rom_output = DIST / f"{NAME}.wsc"
    archive_output = DIST / f"{NAME}.zip"
    manifest_output = DIST / f"{NAME}.manifest.json"
    temporary_archive = DIST / f".{NAME}.zip.tmp"

    shutil.copyfile(ROM_SOURCE, rom_output)
    manifest_output.write_bytes(manifest_data)
    with zipfile.ZipFile(
        temporary_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(f"{NAME}/{relative}", (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
        info = zipfile.ZipInfo(f"{NAME}/SHA256SUMS.json", (1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        archive.writestr(info, manifest_data)
    temporary_archive.replace(archive_output)

    result = {
        "rom": {
            "path": str(rom_output.relative_to(ROOT)),
            "byteCount": rom_output.stat().st_size,
            "sha256": sha256_file(rom_output),
        },
        "archive": {
            "path": str(archive_output.relative_to(ROOT)),
            "byteCount": archive_output.stat().st_size,
            "sha256": sha256_file(archive_output),
        },
        "manifest": {
            "path": str(manifest_output.relative_to(ROOT)),
            "byteCount": manifest_output.stat().st_size,
            "sha256": sha256_file(manifest_output),
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
