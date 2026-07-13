#!/usr/bin/env python3
"""Create a deterministic APF package from dist/ and a compiled Quartus RBF."""

import argparse
import json
import pathlib
import shutil
import tempfile
import zipfile

from build_chip32 import chip32_image
from reverse_rbf import REVERSE


def package_filename(value: object, description: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or any(ord(character) < 0x20 for character in value)
    ):
        raise ValueError(f"{description} must be a nonempty filename")
    path = pathlib.PurePosixPath(value)
    if path.is_absolute() or len(path.parts) != 1 or path.parts[0] in {".", ".."}:
        raise ValueError(f"{description} must not contain a path: {value!r}")
    return value


def create_package(
    *,
    dist: pathlib.Path,
    rbf: pathlib.Path,
    output: pathlib.Path,
    chip32_assembly: pathlib.Path,
    chip32_encoded_image: pathlib.Path,
) -> None:
    dist = dist.resolve()
    rbf = rbf.resolve()
    output = output.resolve()

    if output == rbf:
        raise ValueError("--output must not overwrite --rbf")
    try:
        output.relative_to(dist)
    except ValueError:
        pass
    else:
        raise ValueError("--output must be outside --dist to prevent package self-inclusion")

    # A failed current packaging attempt must not leave an older ZIP looking
    # like its result.
    if output.exists():
        if not output.is_file():
            raise ValueError(f"package output exists and is not a file: {output}")
        output.unlink()

    if not rbf.is_file():
        raise ValueError(f"RBF does not exist or is not a file: {rbf}")
    if rbf.stat().st_size == 0:
        raise ValueError(f"RBF is empty: {rbf}")

    core_json = dist / "Cores/agg23.WonderSwan/core.json"
    try:
        metadata = json.loads(core_json.read_text(encoding="utf-8"))
        core = metadata["core"]
        bitstream_name = package_filename(
            core["cores"][0]["filename"], "core bitstream filename"
        )
        chip32_name = package_filename(
            core["framework"]["chip32_vm"], "Chip32 filename"
        )
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        IndexError,
        TypeError,
    ) as error:
        raise ValueError(f"invalid core definition {core_json}: {error}") from error

    core_directory = dist / "Cores/agg23.WonderSwan"
    if bitstream_name.casefold() == chip32_name.casefold():
        raise ValueError("core bitstream and Chip32 filenames must be distinct")
    existing_names = {path.name.casefold(): path for path in core_directory.iterdir()}
    for filename, description in (
        (bitstream_name, "core bitstream"),
        (chip32_name, "Chip32 image"),
    ):
        existing = existing_names.get(filename.casefold())
        if existing is not None:
            raise ValueError(
                f"refusing to overwrite existing {description} package input: {existing}"
            )

    chip32 = chip32_image(chip32_assembly, chip32_encoded_image)

    with tempfile.TemporaryDirectory(prefix="swan-song-") as temporary:
        stage = pathlib.Path(temporary)
        shutil.copytree(dist, stage, dirs_exist_ok=True)
        stage_core_directory = stage / "Cores/agg23.WonderSwan"
        bitstream = stage_core_directory / bitstream_name
        bitstream.write_bytes(rbf.read_bytes().translate(REVERSE))
        (stage_core_directory / chip32_name).write_bytes(chip32)

        forbidden = {".ws", ".wsc", ".rom", ".sav"}
        leaked = [path for path in stage.rglob("*") if path.suffix.lower() in forbidden]
        if leaked:
            raise ValueError(
                "refusing to package ROM/BIOS/save files: " + ", ".join(map(str, leaked))
            )

        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False
        ) as temporary_file:
            temporary_output = pathlib.Path(temporary_file.name)
        try:
            # Stored entries avoid zlib-version-dependent output bytes. The
            # APF bitstream is small enough that strict cross-host package
            # reproducibility is more valuable than ZIP compression here.
            with zipfile.ZipFile(
                temporary_output, "w", zipfile.ZIP_STORED
            ) as archive:
                for path in sorted(stage.rglob("*")):
                    relative = path.relative_to(stage).as_posix()
                    if path.is_dir():
                        relative += "/"
                    info = zipfile.ZipInfo(relative, (1980, 1, 1, 0, 0, 0))
                    # ZipInfo otherwise records the current host OS, making Windows
                    # and Unix builds differ despite identical inputs.
                    info.create_system = 3
                    info.compress_type = zipfile.ZIP_STORED
                    if path.is_dir():
                        info.external_attr = (0o40755 << 16) | 0x10
                        archive.writestr(info, b"")
                    else:
                        info.external_attr = 0o100644 << 16
                        archive.writestr(info, path.read_bytes())
            temporary_output.replace(output)
        finally:
            temporary_output.unlink(missing_ok=True)


def main() -> None:
    root = pathlib.Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--rbf", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--dist", default=root / "dist", type=pathlib.Path)
    parser.add_argument(
        "--chip32-assembly",
        default=root / "src/support/chip32.asm",
        type=pathlib.Path,
    )
    parser.add_argument(
        "--chip32-encoded-image",
        default=root / "src/support/chip32.bin.hex",
        type=pathlib.Path,
    )
    args = parser.parse_args()

    try:
        create_package(
            dist=args.dist,
            rbf=args.rbf,
            output=args.output,
            chip32_assembly=args.chip32_assembly,
            chip32_encoded_image=args.chip32_encoded_image,
        )
    except ValueError as error:
        parser.error(str(error))

    print(args.output.resolve())


if __name__ == "__main__":
    main()
