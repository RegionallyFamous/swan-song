#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <utility>
#include <vector>

namespace swansong::rom {

constexpr std::size_t kMinimumCompactSize = 64u * 1024u;
constexpr std::size_t kMaximumSize = 16u * 1024u * 1024u;
constexpr std::size_t kBankSize = 64u * 1024u;
constexpr std::size_t kFooterSize = 16u;

inline bool is_power_of_two(std::size_t value) {
  return value != 0 && (value & (value - 1)) == 0;
}

inline std::size_t next_power_of_two(std::size_t value) {
  std::size_t result = 1;
  while (result < value) result <<= 1;
  return result;
}

inline std::size_t header_size_bytes(uint8_t code) {
  switch (code) {
    case 0x00: return 128u * 1024u;
    case 0x01: return 256u * 1024u;
    case 0x02: return 512u * 1024u;
    case 0x03: return 1u * 1024u * 1024u;
    case 0x04: return 2u * 1024u * 1024u;
    case 0x05: return 3u * 1024u * 1024u;
    case 0x06: return 4u * 1024u * 1024u;
    case 0x07: return 6u * 1024u * 1024u;
    case 0x08: return 8u * 1024u * 1024u;
    case 0x09: return 16u * 1024u * 1024u;
    default: return 0;
  }
}

inline bool supported_save_type(uint8_t code) {
  switch (code) {
    case 0x00:
    case 0x01:
    case 0x02:
    case 0x03:
    case 0x04:
    case 0x05:
    case 0x10:
    case 0x20:
    case 0x50:
      return true;
    default:
      return false;
  }
}

struct PreparedImage {
  std::vector<uint8_t> mapped;
  std::size_t raw_size = 0;
  std::size_t prefix_size = 0;
  bool compact = false;
};

// Preserve the historical power-of-two path exactly. The stricter alignment
// and footer checks apply only to newly supported compact images.
inline PreparedImage prepare(const std::vector<uint8_t>& raw) {
  if (raw.size() < kFooterSize || raw.size() > kMaximumSize) {
    throw std::runtime_error("ROM size must be between 16 bytes and 16 MiB");
  }
  if (is_power_of_two(raw.size())) {
    return {raw, raw.size(), 0, false};
  }
  if (raw.size() < kMinimumCompactSize || raw.size() % kBankSize != 0) {
    throw std::runtime_error(
        "non-power-of-two ROM size must be 64 KiB-aligned within 64 KiB..16 MiB");
  }

  const std::size_t aperture = next_power_of_two(raw.size());
  if (aperture > kMaximumSize) {
    throw std::runtime_error("non-power-of-two ROM exceeds the 16 MiB mapper aperture");
  }

  const auto footer = raw.end() - static_cast<std::ptrdiff_t>(kFooterSize);
  if (footer[0] != 0xea) {
    throw std::runtime_error("non-power-of-two ROM footer entry must begin with 0xEA");
  }
  if ((footer[5] & 0x0f) != 0) {
    throw std::runtime_error("non-power-of-two ROM footer maintenance low bits must be zero");
  }
  if ((footer[7] & 0xfe) != 0) {
    throw std::runtime_error("non-power-of-two ROM footer color field is invalid");
  }
  const std::size_t declared_size = header_size_bytes(footer[10]);
  if (declared_size == 0 ||
      (declared_size != raw.size() && declared_size != aperture)) {
    throw std::runtime_error(
        "non-power-of-two ROM footer size does not match its file or mapper aperture");
  }
  if (!supported_save_type(footer[11])) {
    throw std::runtime_error("non-power-of-two ROM footer save type is unsupported");
  }
  if ((footer[12] & 0x04) == 0) {
    throw std::runtime_error("non-power-of-two ROM footer must select the 16-bit ROM bus");
  }
  if (footer[13] > 1) {
    throw std::runtime_error("non-power-of-two ROM footer mapper is unsupported");
  }

  uint16_t checksum = 0;
  for (std::size_t index = 0; index < raw.size() - 2; ++index) {
    checksum = static_cast<uint16_t>(checksum + raw[index]);
  }
  const uint16_t stored = static_cast<uint16_t>(
      raw[raw.size() - 2] | (static_cast<uint16_t>(raw.back()) << 8));
  if (stored != checksum) {
    throw std::runtime_error("non-power-of-two ROM footer checksum mismatch");
  }

  const std::size_t prefix = aperture - raw.size();
  std::vector<uint8_t> mapped(aperture, 0xff);
  std::copy(raw.begin(), raw.end(), mapped.begin() + prefix);
  return {std::move(mapped), raw.size(), prefix, true};
}

}  // namespace swansong::rom
