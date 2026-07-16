#!/usr/bin/env python3
"""Golden and source-contract tests for generated Open IPL v3 boot memories."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import generate_open_ipl as generator


GOLDEN_SHA256 = {
    ("mono", False, False): "e1b7ee7ebec3f8a33c820ab10cf1b5bf0dca69398ea60af1e927f63bacd2e37b",
    ("mono", True, False): "f09f71dd46c17c9ebd82a938e0bbec4dace64874e49e6d53ed6efe3a25277305",
    ("mono", False, True): "d9cf49878ab45566e34b26bf4cadebdb512c0ed89f75be64c1e54020272bd018",
    ("mono", True, True): "ccfaa2ec7e667bc4db679d42a63e1e7a5717573381cd63c84854777f2d08c7e1",
    ("color", False, False): "a7f4453af0d2b624d732111d572679b72cb72fc27498eef98f198e3dbe75d5b2",
    ("color", True, False): "ef648b0dee18f75549718246f59b2b893388e2012f770ad9f9403f78e224712b",
    ("color", False, True): "d2f5aef0e48bb51dca4f46114a207157f64ee6ac92058555b79117a8ebc474a3",
    ("color", True, True): "164a1d11d3c78aca30f6237c8285fd0aaadae0168db8fcd6ba47f2a4cc452c5b",
}


def bytes_from_words(values: list[int]) -> bytes:
    result = bytearray()
    for value in values:
        result.extend((value & 0xFF, value >> 8))
    return bytes(result)


def parse_generated_variants(model: generator.Model) -> dict[str, bytes]:
    source = model.rtl_path.read_text(encoding="utf-8")
    block = source.split(generator.GENERATED_BEGIN, 1)[1].split(
        generator.GENERATED_END, 1
    )[0]
    base_section, function_section = block.split(
        "   function open_ipl_read_word", 1
    )
    base = [generator.NOP_WORD] * (model.size // 2)
    for index, value in re.findall(
        r'^\s+(\d+) => x"([0-9A-F]{4})",$', base_section, re.MULTILINE
    ):
        base[int(index)] = int(value, 16)

    variants: dict[str, bytes] = {}
    case_sections = re.split(r'^\s+when "([01]{2})" =>\s*$', function_section, flags=re.MULTILINE)
    if len(case_sections) != 9:
        raise AssertionError("generated VHDL does not contain exactly four variants")
    for offset in range(1, len(case_sections), 2):
        name = case_sections[offset]
        section = case_sections[offset + 1]
        values = list(base)
        for index, value in re.findall(
            r'^\s+when (\d+) => return x"([0-9A-F]{4})";$',
            section,
            re.MULTILINE,
        ):
            values[int(index)] = int(value, 16)
        variants[name] = bytes_from_words(values)
    return variants


class OpenIPLGenerationTests(unittest.TestCase):
    def test_all_fpga_variants_match_golden_hashes_and_layout(self) -> None:
        observed = {}
        for model in generator.MODELS:
            self.assertEqual(model.size, 8192 if model.color else 4096)
            for protect_owner_area in (False, True):
                for word_width in (False, True):
                    image = generator.make_open_ipl(
                        color=model.color,
                        word_width=word_width,
                        protect_owner_area=protect_owner_area,
                    )
                    key = (model.name, word_width, protect_owner_area)
                    observed[key] = hashlib.sha256(image).hexdigest()
                    self.assertEqual(len(image), model.size)
                    self.assertEqual(
                        image[-generator.RESET_VECTOR_FROM_END :][:5],
                        bytes((0xEA, 0x00, 0x00, 0xF0, 0xFF)),
                    )
                    self.assertEqual(
                        image[-generator.STARTUP_FROM_END],
                        0xFA,
                    )
                    startup_length = 121 + (4 if model.color else 0) + (
                        4 if protect_owner_area else 0
                    )
                    startup_end = model.size - generator.STARTUP_FROM_END + startup_length
                    reset_start = model.size - generator.RESET_VECTOR_FROM_END
                    self.assertEqual(
                        image[startup_end:reset_start],
                        bytes((generator.NOP,)) * (reset_start - startup_end),
                    )
                    hardware_flags = 0x81 | (0x02 if model.color else 0) | (
                        0x04 if word_width else 0
                    )
                    self.assertIn(
                        bytes((0xC6, 0x06, 0x01, 0x04, hardware_flags)),
                        image,
                    )
                    self.assertIn(bytes((0xB8, hardware_flags, 0xFF, 0xEA)), image)
                    protection = bytes((0xB0, 0x80, 0xE6, 0xBE))
                    self.assertEqual(protection in image, protect_owner_area)
        self.assertEqual(observed, GOLDEN_SHA256)

    def test_generated_vhdl_reconstructs_every_golden_variant(self) -> None:
        for model in generator.MODELS:
            variants = parse_generated_variants(model)
            self.assertEqual(set(variants), {"00", "01", "10", "11"})
            for protect_owner_area in (False, True):
                for word_width in (False, True):
                    name = f"{int(protect_owner_area)}{int(word_width)}"
                    expected = generator.make_open_ipl(
                        color=model.color,
                        word_width=word_width,
                        protect_owner_area=protect_owner_area,
                    )
                    self.assertEqual(variants[name], expected)
                    self.assertEqual(
                        hashlib.sha256(variants[name]).hexdigest(),
                        GOLDEN_SHA256[
                            (model.name, word_width, protect_owner_area)
                        ],
                    )

    def test_checked_in_generated_blocks_are_current(self) -> None:
        for model in generator.MODELS:
            source = model.rtl_path.read_text(encoding="utf-8")
            expected = generator.replace_generated_block(
                source, generator.render_generated_block(model), model.rtl_path
            )
            self.assertEqual(source, expected)
        self.assertEqual(
            generator.CPP_PATH.read_text(encoding="utf-8"),
            generator.render_cpp_header(),
        )

    def test_generated_cpp_make_reconstructs_every_golden_variant(self) -> None:
        compiler = (
            shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
        )
        self.assertIsNotNone(compiler, "a C++17 compiler is required for Open IPL tests")
        helper_source = f'''\
#include <cstddef>
#include <iostream>
#include "{generator.CPP_PATH.as_posix()}"

int main() {{
  std::cout << swansong::open_ipl::kIdentity << '\\n';
  for (int color = 0; color < 2; ++color) {{
    for (int protect = 0; protect < 2; ++protect) {{
      for (int width = 0; width < 2; ++width) {{
        const auto image = swansong::open_ipl::make(
            color != 0, width != 0, protect != 0);
        std::cout.write(reinterpret_cast<const char*>(image.data()),
                        static_cast<std::streamsize>(image.size()));
      }}
    }}
  }}
}}
'''
        with tempfile.TemporaryDirectory(prefix="swansong-open-ipl-") as directory:
            helper = Path(directory) / "open_ipl_helper"
            compiled = subprocess.run(
                [
                    str(compiler),
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-x",
                    "c++",
                    "-",
                    "-o",
                    str(helper),
                ],
                input=helper_source,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            completed = subprocess.run(
                [str(helper)], capture_output=True, check=True
            )

        identity, payload = completed.stdout.split(b"\n", 1)
        self.assertEqual(identity, b"open-bootstrap-v3")
        offset = 0
        for model in generator.MODELS:
            for protect_owner_area in (False, True):
                for word_width in (False, True):
                    observed = payload[offset : offset + model.size]
                    offset += model.size
                    expected = generator.make_open_ipl(
                        color=model.color,
                        word_width=word_width,
                        protect_owner_area=protect_owner_area,
                    )
                    self.assertEqual(observed, expected)
                    self.assertEqual(
                        hashlib.sha256(observed).hexdigest(),
                        GOLDEN_SHA256[
                            (model.name, word_width, protect_owner_area)
                        ],
                    )
        self.assertEqual(offset, len(payload))

    def test_generated_cpp_header_is_compact_tail_storage(self) -> None:
        source = generator.CPP_PATH.read_text(encoding="utf-8")
        self.assertEqual(source.count("Tail{{  //"), 8)
        self.assertIn("kTailSize = 256u", source)
        self.assertIn("color ? 8192u : 4096u, 0x90u", source)
        self.assertIn("image.end() - kTailSize", source)
        self.assertNotIn("std::array<std::uint8_t, 4096", source)
        self.assertNotIn("std::array<std::uint8_t, 8192", source)

    def test_each_model_has_one_initialized_memory_and_registered_read(self) -> None:
        for model in generator.MODELS:
            source = model.rtl_path.read_text(encoding="utf-8")
            self.assertEqual(source.count("signal rom : t_rom := OPEN_IPL_WORDS;"), 1)
            self.assertEqual(source.count("type t_rom is array"), 1)
            self.assertEqual(
                source.count('attribute ramstyle of rom : signal is "M10K";'), 1
            )
            self.assertIn("word_width         : in std_logic := '0'", source)
            self.assertIn("protect_owner_area : in std_logic := '1'", source)
            self.assertNotIn("bios_wr", source)
            read_process = re.search(
                r"process \(clk\).*?if rising_edge\(clk\) then\s+"
                r"read_address <= address;\s+"
                r"read_data\s+<= rom\(to_integer\(unsigned\(address\)\)\);"
                r".*?end if;\s+end process;",
                source,
                re.DOTALL,
            )
            self.assertIsNotNone(read_process)
            self.assertRegex(
                source,
                r"data <= open_ipl_read_word\(\s+"
                r"to_integer\(unsigned\(read_address\)\),\s+read_data,",
            )

    def test_reset_vectors_use_little_endian_word_storage(self) -> None:
        for model in generator.MODELS:
            source_variants = parse_generated_variants(model)
            for image in source_variants.values():
                values = generator.words(image)
                reset_word = (model.size - generator.RESET_VECTOR_FROM_END) // 2
                self.assertEqual(
                    values[reset_word : reset_word + 3],
                    (0x00EA, 0xF000, 0x90FF),
                )


if __name__ == "__main__":
    unittest.main()
