#!/usr/bin/env python3
"""Adversarial tests for the open WonderSwan SRAM persistence probes."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import generate_sram_persistence_probes as probes


EXPECTED_GENERATOR_SHA256 = (
    "f5686a474a39806def97a5b9396c8ef9e4e05f18697fe335b9d438757de29ac4"
)
EXPECTED_OUTPUT_SHA256 = {
    "sram_type03_persistence.ws": (
        "1c04f468ac445616e9613b08dd874aadc83bc214f9b192f777e845019b4c4ccb"
    ),
    "sram_type03_persistence.wsc": (
        "1ea9323cf4300d5667eb10bde448c7b013e82d39d2e92757d792377bb6a856a1"
    ),
    "sram_type04_persistence.ws": (
        "e44785c8c117bd10519a96a699512c16bd23889f206b763f95f1c1e40c7b36c9"
    ),
    "sram_type04_persistence.wsc": (
        "b1c6d141ddd59871806e76a7ab9b5e5c2a2b2ae768bcb41eac37ad53cda73d94"
    ),
    "sram_type05_persistence.ws": (
        "42b82002ee3f5f82c12b6ceb4d34015d36490d1321594c77d785e669c0749311"
    ),
    "sram_type05_persistence.wsc": (
        "3eb97b9f40c22c097772a7c74c6c39d7fe1a913e3008237398431422b49cb1c2"
    ),
}
EXPECTED_CONTROL_SHA256 = {
    "sram_persistence_probes.manifest.json": (
        "cdd51d0499d22bb4646a883b0f56f1b4407d9757f0bde66b4bbdd141f8aac172"
    ),
    "sram_persistence_probes.sha256": (
        "a57d61006e2226db52d88c6144c80ed14d87c3a71b0872f19b1086af9e28d048"
    ),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def signed8(value: int) -> int:
    return value - 0x100 if value & 0x80 else value


def signed16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


class ProbeMachine:
    """Independent interpreter for the generator's intentionally tiny ISA."""

    def __init__(self, program: bytes, sram: bytearray, save_type: int, model: str):
        self.code = program
        self.sram = sram
        self.save_type = save_type
        self.model = model
        self.iram = bytearray(0x10000)
        self.reg = {"ax": 0, "bx": 0, "cx": 0, "dx": 0}
        self.ds = 0
        self.bank = 0
        self.ip = 0
        self.zero = False
        self.stack: list[int] = []

    def byte(self) -> int:
        if self.ip >= len(self.code):
            raise AssertionError("probe executed beyond its authored program")
        value = self.code[self.ip]
        self.ip += 1
        return value

    def word(self) -> int:
        return self.byte() | (self.byte() << 8)

    def read_byte(self, offset: int) -> int:
        if self.ds == 0:
            return self.iram[offset]
        if self.ds != 0x1000:
            raise AssertionError(f"unexpected data segment 0x{self.ds:04x}")
        address = ((self.bank << 16) | offset) & (len(self.sram) - 1)
        return self.sram[address]

    def write_byte(self, offset: int, value: int) -> None:
        if self.ds == 0:
            self.iram[offset] = value & 0xFF
            return
        if self.ds != 0x1000:
            raise AssertionError(f"unexpected data segment 0x{self.ds:04x}")
        address = ((self.bank << 16) | offset) & (len(self.sram) - 1)
        self.sram[address] = value & 0xFF

    def read_word(self, offset: int) -> int:
        return self.read_byte(offset) | (self.read_byte(offset + 1) << 8)

    def write_word(self, offset: int, value: int) -> None:
        self.write_byte(offset, value)
        self.write_byte(offset + 1, value >> 8)

    def relative8(self) -> None:
        self.ip += signed8(self.byte())

    def relative16(self) -> int:
        displacement = signed16(self.word())
        return self.ip + displacement

    def run(self) -> int:
        for _ in range(10_000):
            start = self.ip
            opcode = self.byte()
            if opcode == 0xFA:  # cli
                continue
            if 0xB8 <= opcode <= 0xBF:  # mov r16, imm16
                registers = ("ax", "cx", "dx", "bx", "sp", "bp", "si", "di")
                register = registers[opcode - 0xB8]
                if register not in self.reg:
                    raise AssertionError(f"unsupported word register {register}")
                self.reg[register] = self.word()
                continue
            if 0xB0 <= opcode <= 0xB7:  # mov r8, imm8
                if opcode != 0xB0:
                    raise AssertionError(f"unsupported byte register opcode {opcode:02x}")
                self.reg["ax"] = (self.reg["ax"] & 0xFF00) | self.byte()
                continue
            if opcode == 0x8E:
                if self.byte() != 0xD8:
                    raise AssertionError("unsupported mov segment encoding")
                self.ds = self.reg["ax"]
                continue
            if opcode == 0xE6:
                port = self.byte()
                value = self.reg["ax"] & 0xFF
                if port != 0xC1:
                    raise AssertionError(f"unexpected probe output port 0x{port:02x}")
                self.bank = value
                continue
            if opcode == 0x81:
                if self.byte() != 0x3E:
                    raise AssertionError("unsupported immediate compare encoding")
                offset = self.word()
                self.zero = self.read_word(offset) == self.word()
                continue
            if opcode == 0xC7:
                if self.byte() != 0x06:
                    raise AssertionError("unsupported word store encoding")
                self.write_word(self.word(), self.word())
                continue
            if opcode in (0x74, 0x75):
                displacement = signed8(self.byte())
                taken = self.zero if opcode == 0x74 else not self.zero
                if taken:
                    self.ip += displacement
                continue
            if opcode == 0xE9:
                target = self.relative16()
                if target == start:
                    self.assert_published()
                    return self.iram[0x0400]
                self.ip = target
                continue
            if opcode == 0xE8:
                target = self.relative16()
                self.stack.append(self.ip)
                self.ip = target
                continue
            if opcode == 0xC3:
                if not self.stack:
                    raise AssertionError("probe returned without a call")
                self.ip = self.stack.pop()
                continue
            if opcode == 0x31:
                modrm = self.byte()
                if modrm == 0xC0:
                    self.reg["ax"] = 0
                elif modrm == 0xD2:
                    self.reg["dx"] = 0
                else:
                    raise AssertionError(f"unsupported xor encoding 31 {modrm:02x}")
                self.zero = True
                continue
            if opcode == 0x88:
                modrm = self.byte()
                if modrm == 0xD0:  # mov al, dl
                    self.reg["ax"] = (
                        (self.reg["ax"] & 0xFF00) | (self.reg["dx"] & 0xFF)
                    )
                elif modrm == 0xC2:  # mov dl, al
                    self.reg["dx"] = (
                        (self.reg["dx"] & 0xFF00) | (self.reg["ax"] & 0xFF)
                    )
                elif modrm == 0x16:  # mov [disp16], dl
                    self.write_byte(self.word(), self.reg["dx"] & 0xFF)
                else:
                    raise AssertionError(f"unsupported mov byte encoding 88 {modrm:02x}")
                continue
            if opcode == 0xC6:
                if self.byte() != 0x06:
                    raise AssertionError("unsupported byte store encoding")
                self.write_byte(self.word(), self.byte())
                continue
            if opcode == 0x89:
                if self.byte() != 0xD8:
                    raise AssertionError("unsupported register move encoding")
                self.reg["ax"] = self.reg["bx"]
                continue
            if opcode == 0x01:
                if self.byte() != 0xD0:
                    raise AssertionError("unsupported add encoding")
                self.reg["ax"] = (self.reg["ax"] + self.reg["dx"]) & 0xFFFF
                continue
            if opcode == 0xA3:
                self.write_word(self.word(), self.reg["ax"])
                continue
            if opcode == 0xF7:
                if self.byte() != 0xD0:
                    raise AssertionError("unsupported not encoding")
                self.reg["ax"] ^= 0xFFFF
                continue
            if opcode == 0x39:
                if self.byte() != 0x06:
                    raise AssertionError("unsupported memory compare encoding")
                self.zero = self.read_word(self.word()) == self.reg["ax"]
                continue
            if opcode == 0x42:
                self.reg["dx"] = (self.reg["dx"] + 1) & 0xFFFF
                continue
            if opcode == 0xE2:
                displacement = signed8(self.byte())
                self.reg["cx"] = (self.reg["cx"] - 1) & 0xFFFF
                if self.reg["cx"]:
                    self.ip += displacement
                continue
            raise AssertionError(
                f"unsupported authored opcode 0x{opcode:02x} at 0x{start:04x}"
            )
        raise AssertionError("probe did not publish a result before instruction limit")

    def assert_published(self) -> None:
        if self.iram[0x0401] != self.save_type:
            raise AssertionError("probe did not publish its exact footer save type")
        if self.iram[0x0402] != probes.MODELS[self.model]:
            raise AssertionError("probe did not publish its exact console model")


def run_boot(
    save_type: int,
    model: str,
    sram: bytearray,
    *,
    code: bytes | None = None,
) -> int:
    return ProbeMachine(
        probes.program(save_type, model) if code is None else code,
        sram,
        save_type,
        model,
    ).run()


class PersistenceProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="swan-sram-persistence-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "bundle"
        probes.generate(self.bundle)

    def fresh_copy(self, name: str) -> Path:
        destination = self.root / name
        shutil.copytree(self.bundle, destination)
        return destination

    def test_source_outputs_and_bundle_are_exactly_hash_bound(self) -> None:
        source = Path(probes.__file__).resolve().read_bytes()
        self.assertEqual(sha256(source), EXPECTED_GENERATOR_SHA256)
        document = probes.verify_bundle(self.bundle)
        self.assertFalse(document["commercial_rom_bytes"])
        self.assertEqual(
            document["content_origin"],
            "repository-authored-machine-code-metadata-and-padding-only",
        )
        self.assertEqual(document["generator"]["sha256"], EXPECTED_GENERATOR_SHA256)
        self.assertEqual(set(document["outputs"]), set(EXPECTED_OUTPUT_SHA256))
        for name, expected in EXPECTED_OUTPUT_SHA256.items():
            self.assertEqual(sha256((self.bundle / name).read_bytes()), expected)
            self.assertEqual(document["outputs"][name]["sha256"], expected)
        for name, expected in EXPECTED_CONTROL_SHA256.items():
            self.assertEqual(sha256((self.bundle / name).read_bytes()), expected)
        self.assertEqual(self.bundle.stat().st_mode & 0o777, 0o700)
        self.assertEqual(
            {path.stat().st_mode & 0o777 for path in self.bundle.iterdir()},
            {0o600},
        )

    def test_generation_is_byte_deterministic_and_supports_model_subsets(self) -> None:
        second = self.root / "second"
        probes.generate(second, models=("wsc", "ws"))
        first_files = {path.name: path.read_bytes() for path in self.bundle.iterdir()}
        second_files = {path.name: path.read_bytes() for path in second.iterdir()}
        self.assertEqual(first_files, second_files)

        mono = self.root / "mono"
        probes.generate(mono, models=("ws",))
        document = probes.verify_bundle(mono)
        self.assertEqual(document["models"], ["ws"])
        self.assertEqual(
            set(document["outputs"]),
            {probes.rom_name(save_type, "ws") for save_type in probes.SAVE_TYPES},
        )

    def test_manifest_binds_production_open_ipl_variants(self) -> None:
        document = probes.verify_bundle(self.bundle)
        self.assertEqual(len(document["probes"]), 6)
        for item in document["probes"]:
            model = item["model"]
            self.assertEqual(item["open_ipl_identity"], probes.OPEN_IPL_IDENTITY)
            self.assertEqual(
                item["open_ipl_variant"], probes.OPEN_IPL_VARIANTS[model]
            )
            self.assertNotIn("simulation_bootstrap", item)

    def test_roms_are_legal_checksummed_authored_images(self) -> None:
        for model, color in probes.MODELS.items():
            for save_type in probes.SAVE_TYPES:
                with self.subTest(model=model, save_type=save_type):
                    rom = (self.bundle / probes.rom_name(save_type, model)).read_bytes()
                    payload = probes.program(save_type, model)
                    self.assertEqual(len(rom), probes.ROM_SIZE)
                    self.assertEqual(
                        rom[probes.PROGRAM_OFFSET : probes.PROGRAM_OFFSET + len(payload)],
                        payload,
                    )
                    self.assertEqual(
                        rom[
                            probes.MARKER_OFFSET :
                            probes.MARKER_OFFSET + len(probes.PROVENANCE_MARKER)
                        ],
                        probes.PROVENANCE_MARKER,
                    )
                    self.assertEqual(rom[: probes.PROGRAM_OFFSET], b"\xFF" * probes.PROGRAM_OFFSET)
                    self.assertEqual(
                        rom[probes.PROGRAM_OFFSET + len(payload) : probes.MARKER_OFFSET],
                        b"\xFF" * (
                            probes.MARKER_OFFSET
                            - probes.PROGRAM_OFFSET
                            - len(payload)
                        ),
                    )
                    marker_end = probes.MARKER_OFFSET + len(probes.PROVENANCE_MARKER)
                    self.assertEqual(
                        rom[marker_end : probes.FOOTER_OFFSET],
                        b"\xFF" * (probes.FOOTER_OFFSET - marker_end),
                    )
                    self.assertEqual(rom[probes.FOOTER_OFFSET], 0xEA)
                    self.assertEqual(rom[probes.FOOTER_OFFSET + 7], color)
                    self.assertEqual(rom[probes.FOOTER_OFFSET + 10], 0x04)
                    self.assertEqual(rom[probes.FOOTER_OFFSET + 11], save_type)
                    self.assertEqual(rom[probes.FOOTER_OFFSET + 12], 0x04)
                    self.assertEqual(rom[probes.FOOTER_OFFSET + 13], 0x00)
                    self.assertEqual(
                        int.from_bytes(rom[-2:], "little"), sum(rom[:-2]) & 0xFFFF
                    )

    def test_program_initializes_then_checks_and_toggles_persisted_data(self) -> None:
        for model in probes.MODELS:
            for save_type, save in probes.SAVE_TYPES.items():
                with self.subTest(model=model, save_type=save_type):
                    sram = bytearray(save.bytes)
                    self.assertEqual(
                        run_boot(save_type, model, sram), probes.STATUS_INITIALIZED
                    )
                    self.assertEqual(sram[0x0004:0x0007], bytes((0x11, save_type, probes.MODELS[model])))
                    first = bytes(sram)
                    self.assertEqual(
                        run_boot(save_type, model, sram),
                        probes.STATUS_PERSISTED_1_TO_2,
                    )
                    self.assertEqual(sram[0x0004], probes.STATUS_PERSISTED_1_TO_2)
                    second = bytes(sram)
                    self.assertNotEqual(first, second)
                    self.assertEqual(
                        run_boot(save_type, model, sram),
                        probes.STATUS_PERSISTED_2_TO_1,
                    )
                    self.assertEqual(sram[0x0004], probes.STATUS_PERSISTED_2_TO_1)
                    self.assertEqual(sram[:4], first[:4])
                    self.assertEqual(sram[7:], first[7:])
                    for bank in range(save.banks):
                        low = bank * 0x10000 + 0x0100
                        high = bank * 0x10000 + 0xFFFE
                        expected = (probes.PATTERN_1 + bank) & 0xFFFF
                        self.assertEqual(int.from_bytes(sram[low : low + 2], "little"), expected)
                        self.assertEqual(
                            int.from_bytes(sram[high : high + 2], "little"),
                            expected ^ 0xFFFF,
                        )

    def test_persisted_corruption_and_undersized_aliasing_fail_closed(self) -> None:
        for save_type, save in probes.SAVE_TYPES.items():
            with self.subTest(corrupt=save_type):
                sram = bytearray(save.bytes)
                self.assertEqual(
                    run_boot(save_type, "ws", sram), probes.STATUS_INITIALIZED
                )
                sram[0x0100] ^= 1
                self.assertEqual(run_boot(save_type, "ws", sram), probes.STATUS_FAILURE)
                self.assertEqual(sram[0x0004], probes.STATUS_FAILURE)

        for save_type in (0x04, 0x05):
            with self.subTest(alias=save_type):
                inherited_128k_mask = bytearray(128 * 1024)
                self.assertEqual(
                    run_boot(save_type, "ws", inherited_128k_mask),
                    probes.STATUS_FAILURE,
                )

    def test_header_only_or_nonchecking_payload_cannot_satisfy_behavior(self) -> None:
        for save_type, save in probes.SAVE_TYPES.items():
            with self.subTest(save_type=save_type):
                header_only = bytes((0xE9, 0xFD, 0xFF))
                with self.assertRaisesRegex(AssertionError, "exact footer save type"):
                    run_boot(save_type, "ws", bytearray(save.bytes), code=header_only)

    def test_bundle_mutations_are_rejected(self) -> None:
        code_tamper = self.fresh_copy("code-tamper")
        target = code_tamper / probes.rom_name(0x03, "ws")
        changed = bytearray(target.read_bytes())
        changed[probes.PROGRAM_OFFSET] ^= 1
        target.write_bytes(changed)
        with self.assertRaisesRegex(ValueError, "source/output contract mismatch"):
            probes.verify_bundle(code_tamper)

        footer_tamper = self.fresh_copy("footer-tamper")
        target = footer_tamper / probes.rom_name(0x04, "wsc")
        changed = bytearray(target.read_bytes())
        changed[probes.FOOTER_OFFSET + 11] = 0x03
        changed[-2:] = (sum(changed[:-2]) & 0xFFFF).to_bytes(2, "little")
        target.write_bytes(changed)
        with self.assertRaisesRegex(ValueError, "source/output contract mismatch"):
            probes.verify_bundle(footer_tamper)

        manifest_tamper = self.fresh_copy("manifest-tamper")
        path = manifest_tamper / probes.MANIFEST_NAME
        document = json.loads(path.read_text(encoding="utf-8"))
        document["generator"]["sha256"] = "0" * 64
        path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source/output contract mismatch"):
            probes.verify_bundle(manifest_tamper)

        representation_tamper = self.fresh_copy("manifest-representation-tamper")
        path = representation_tamper / probes.MANIFEST_NAME
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "not exact canonical bytes"):
            probes.verify_bundle(representation_tamper)

        duplicate = self.fresh_copy("duplicate-manifest")
        path = duplicate / probes.MANIFEST_NAME
        original = path.read_text(encoding="utf-8")
        path.write_text('{"schema":"duplicate",' + original[1:], encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate manifest field"):
            probes.verify_bundle(duplicate)

        nonstandard = self.fresh_copy("nonstandard-manifest")
        path = nonstandard / probes.MANIFEST_NAME
        path.write_text('{"schema":NaN}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "non-standard JSON constant"):
            probes.verify_bundle(nonstandard)

        checksum_tamper = self.fresh_copy("checksum-tamper")
        path = checksum_tamper / probes.CHECKSUM_NAME
        path.write_bytes(path.read_bytes().replace(b"a", b"b", 1))
        with self.assertRaisesRegex(ValueError, "checksum file mismatch"):
            probes.verify_bundle(checksum_tamper)

        extra = self.fresh_copy("extra")
        (extra / "commercial-carrier.bin").write_bytes(b"not allowed")
        with self.assertRaisesRegex(ValueError, "member set mismatch"):
            probes.verify_bundle(extra)

        extra_directory = self.fresh_copy("extra-directory")
        carrier = extra_directory / "carrier"
        carrier.mkdir()
        (carrier / "commercial.bin").write_bytes(b"not allowed")
        with self.assertRaisesRegex(ValueError, "member set mismatch"):
            probes.verify_bundle(extra_directory)

    def test_invalid_generation_requests_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported SRAM save type"):
            probes.image(0x02, "ws")
        with self.assertRaisesRegex(ValueError, "unsupported WonderSwan model"):
            probes.image(0x03, "other")
        with self.assertRaisesRegex(ValueError, "nonempty and unique"):
            probes.normalize_models(())
        with self.assertRaisesRegex(ValueError, "nonempty and unique"):
            probes.normalize_models(("ws", "ws"))
        nonempty = self.root / "nonempty"
        nonempty.mkdir()
        (nonempty / "carrier.bin").write_bytes(b"not allowed")
        with self.assertRaisesRegex(ValueError, "must not already exist"):
            probes.generate(nonempty)

        empty = self.root / "empty"
        empty.mkdir()
        with self.assertRaisesRegex(ValueError, "must not already exist"):
            probes.generate(empty)

        symlink = self.root / "output-link"
        symlink.symlink_to(self.root / "elsewhere", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "must not already exist"):
            probes.generate(symlink)

        source_link = self.root / "generator-hardlink.py"
        source_link.hardlink_to(Path(probes.__file__).resolve())
        with self.assertRaisesRegex(ValueError, "must not be hard-linked"):
            probes.generate(self.root / "hardlink-source-output", source_path=source_link)

        hardlink_bundle = self.fresh_copy("hardlink-bundle")
        member = hardlink_bundle / probes.rom_name(0x03, "ws")
        carrier = self.root / "member-carrier.bin"
        carrier.write_bytes(member.read_bytes())
        member.unlink()
        member.hardlink_to(carrier)
        with self.assertRaisesRegex(ValueError, "must be one regular file"):
            probes.verify_bundle(hardlink_bundle)


if __name__ == "__main__":
    unittest.main()
