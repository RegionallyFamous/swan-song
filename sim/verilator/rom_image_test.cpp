#include "rom_image.hpp"

#include <cassert>
#include <cstdint>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

std::vector<uint8_t> read_file(const std::string& path) {
  std::ifstream input(path, std::ios::binary);
  if (!input) throw std::runtime_error("cannot read compact-ROM fixture");
  return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}

void restamp(std::vector<uint8_t>& rom) {
  uint16_t checksum = 0;
  for (std::size_t index = 0; index < rom.size() - 2; ++index) {
    checksum = static_cast<uint16_t>(checksum + rom[index]);
  }
  rom[rom.size() - 2] = static_cast<uint8_t>(checksum);
  rom.back() = static_cast<uint8_t>(checksum >> 8);
}

template <typename Mutator>
void expect_rejected(const std::vector<uint8_t>& valid, Mutator mutate) {
  auto changed = valid;
  mutate(changed);
  try {
    (void)swansong::rom::prepare(changed);
  } catch (const std::runtime_error&) {
    return;
  }
  assert(false && "compact-ROM mutation unexpectedly accepted");
}

}  // namespace

int main(int argc, char** argv) {
  assert(argc == 2);
  const auto raw = read_file(argv[1]);
  const auto prepared = swansong::rom::prepare(raw);
  assert(prepared.compact);
  assert(prepared.raw_size == 896u * 1024u);
  assert(prepared.prefix_size == 128u * 1024u);
  assert(prepared.mapped.size() == 1024u * 1024u);
  // Legal upper maintenance flags must not be confused with the reserved
  // low nibble of footer byte 5.
  assert(raw[raw.size() - 11] == 0xa0);
  for (std::size_t index = 0; index < prepared.prefix_size; ++index) {
    assert(prepared.mapped[index] == 0xff);
  }
  assert(std::equal(raw.begin(), raw.end(),
                    prepared.mapped.begin() + prepared.prefix_size));

  expect_rejected(raw, [](auto& rom) { rom.resize(rom.size() - 2); });
  expect_rejected(raw, [](auto& rom) {
    rom[rom.size() - 16] = 0x90;
    restamp(rom);
  });
  expect_rejected(raw, [](auto& rom) {
    rom[rom.size() - 11] |= 0x01;
    restamp(rom);
  });
  expect_rejected(raw, [](auto& rom) {
    rom[rom.size() - 6] = 0x04;
    restamp(rom);
  });
  expect_rejected(raw, [](auto& rom) { rom[0] ^= 1; });

  // This deliberately malformed image preserves the historical direct path:
  // stricter footer checks are not retroactively imposed on power-of-two ROMs.
  const std::vector<uint8_t> legacy_power_of_two(64u * 1024u, 0x00);
  const auto legacy = swansong::rom::prepare(legacy_power_of_two);
  assert(!legacy.compact);
  assert(legacy.prefix_size == 0);
  assert(legacy.mapped == legacy_power_of_two);
  return 0;
}
