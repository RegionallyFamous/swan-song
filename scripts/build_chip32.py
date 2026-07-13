#!/usr/bin/env python3
"""Materialize the pinned Chip32 image without a network/tool dependency.

The textual image is the exact output of open-fpga/bass-chip32 v1.0.0 for
src/support/chip32.asm, including the fixed-name console EEPROM loads added
after agg23's released WonderSwan 1.0.1 image and the bounded post-LOADF compact
ROM validation poll. Keeping the small compiled image as hexadecimal makes the
package build offline and host-independent while the source and output hashes
prevent the checked-in assembly and machine code from silently drifting apart.

Primary sources:
https://github.com/open-fpga/bass-chip32/releases/tag/v1.0.0
https://github.com/agg23/openfpga-wonderswan/releases/tag/1.0.1
https://www.analogue.co/developer/docs/chip32-vm
"""

import argparse
import hashlib
import pathlib


EXPECTED_ASM_SHA256 = "12dfd14ff66ae02aeda69083d8d793ac5a3149b84eaa7f80d319cec642fd98fe"
EXPECTED_IMAGE_SHA256 = "962fbc405da1d119e8f189204fb942eb2368a6bf907da6c8009e491965daf030"
EXPECTED_IMAGE_SIZE = 411


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chip32_image(assembly: pathlib.Path, encoded_image: pathlib.Path) -> bytes:
    try:
        assembly_bytes = assembly.read_bytes()
    except OSError as error:
        raise ValueError(f"cannot read Chip32 assembly {assembly}: {error}") from error
    assembly_digest = sha256(assembly_bytes)
    if assembly_digest != EXPECTED_ASM_SHA256:
        raise ValueError(
            "Chip32 assembly does not match the image source: "
            f"expected sha256={EXPECTED_ASM_SHA256}, got {assembly_digest}"
        )

    try:
        encoded = encoded_image.read_text(encoding="ascii")
    except (OSError, UnicodeError) as error:
        raise ValueError(f"cannot read encoded Chip32 image {encoded_image}: {error}") from error
    try:
        image = bytes.fromhex(encoded)
    except ValueError as error:
        raise ValueError(f"invalid hexadecimal Chip32 image {encoded_image}: {error}") from error

    digest = sha256(image)
    if len(image) != EXPECTED_IMAGE_SIZE or digest != EXPECTED_IMAGE_SHA256:
        raise ValueError(
            "Chip32 image identity mismatch: "
            f"expected size={EXPECTED_IMAGE_SIZE} sha256={EXPECTED_IMAGE_SHA256}, "
            f"got size={len(image)} sha256={digest}"
        )
    return image


def main() -> None:
    root = pathlib.Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--assembly", default=root / "src/support/chip32.asm", type=pathlib.Path
    )
    parser.add_argument(
        "--encoded-image",
        default=root / "src/support/chip32.bin.hex",
        type=pathlib.Path,
    )
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()

    try:
        image = chip32_image(args.assembly, args.encoded_image)
    except ValueError as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(image)
    print(args.output)


if __name__ == "__main__":
    main()
