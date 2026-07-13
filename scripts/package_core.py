#!/usr/bin/env python3
"""Create a deterministic APF package from dist/ and a compiled Quartus RBF."""

import argparse
import json
import pathlib
import shutil
import tempfile
import zipfile

from reverse_rbf import REVERSE


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rbf", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--dist", default="dist", type=pathlib.Path)
    args = parser.parse_args()

    dist = args.dist.resolve()
    rbf = args.rbf.resolve()
    output = args.output.resolve()

    if not rbf.is_file():
        parser.error(f"RBF does not exist or is not a file: {rbf}")
    if rbf.stat().st_size == 0:
        parser.error(f"RBF is empty: {rbf}")
    if output == rbf:
        parser.error("--output must not overwrite --rbf")
    try:
        output.relative_to(dist)
    except ValueError:
        pass
    else:
        parser.error("--output must be outside --dist to prevent package self-inclusion")

    core_json = dist / "Cores/agg23.WonderSwan/core.json"
    metadata = json.loads(core_json.read_text())
    bitstream_name = metadata["core"]["cores"][0]["filename"]

    with tempfile.TemporaryDirectory(prefix="swan-song-") as temporary:
        stage = pathlib.Path(temporary)
        shutil.copytree(dist, stage, dirs_exist_ok=True)
        bitstream = stage / "Cores/agg23.WonderSwan" / bitstream_name
        bitstream.write_bytes(rbf.read_bytes().translate(REVERSE))

        forbidden = {".ws", ".wsc", ".rom", ".sav"}
        leaked = [path for path in stage.rglob("*") if path.suffix.lower() in forbidden]
        if leaked:
            raise SystemExit("refusing to package ROM/BIOS/save files: " + ", ".join(map(str, leaked)))

        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(stage.rglob("*")):
                relative = path.relative_to(stage).as_posix()
                if path.is_dir():
                    relative += "/"
                info = zipfile.ZipInfo(relative, (1980, 1, 1, 0, 0, 0))
                # ZipInfo otherwise records the current host OS, making Windows
                # and Unix builds differ despite identical inputs.
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED
                if path.is_dir():
                    info.external_attr = (0o40755 << 16) | 0x10
                    archive.writestr(info, b"", compresslevel=9)
                else:
                    info.external_attr = 0o100644 << 16
                    archive.writestr(info, path.read_bytes(), compresslevel=9)

    print(output)


if __name__ == "__main__":
    main()
