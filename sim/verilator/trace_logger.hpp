// SPDX-License-Identifier: GPL-2.0-only
#pragma once

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <ios>
#include <memory>
#include <optional>
#include <ostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace swansong::trace {

enum class EventType : uint8_t {
  Cpu = 1,
  Bank = 2,
  Vram = 4,
  Mem = 8,
  BgCell = 16,
  SpriteRow = 32,
};
enum class Format { Auto, Csv, Jsonl };
enum class VramRole : uint8_t {
  Screen1Map = 0,
  Screen1Tile = 1,
  Screen2Map = 2,
  Screen2Tile = 3,
  SpriteTable = 4,
  SpriteTile = 5,
};

enum class MemInitiator : uint8_t { Cpu = 0, Gdma = 1, Sdma = 2 };
enum class MemAccess : uint8_t { Read = 0, Write = 1 };
enum class MemSpace : uint8_t {
  Iram = 1,
  CartSram = 2,
  CartRom0 = 3,
  CartRom1 = 4,
  CartRomLinear = 5,
  BootRom = 6,
  Unmapped = 7,
  AbsentSram = 8,
};
enum class OriginStatus : uint8_t {
  Exact = 1,
  Unattributed = 2,
  NotApplicable = 3,
};

constexpr uint8_t kAllMemInitiators = 0x07;
constexpr uint8_t kAllMemAccesses = 0x03;
constexpr uint16_t kAllMemSpaces = 0x01fe;
constexpr uint8_t kAllOriginStatuses = 0x0e;

constexpr uint8_t kAllVramRoles = (1u << 6) - 1;

struct PcRange {
  uint32_t first;
  uint32_t last;

  bool contains(uint32_t pc) const { return pc >= first && pc <= last; }
};

struct AddressRange {
  uint16_t first;
  uint16_t last;

  bool contains(uint16_t address) const {
    return address >= first && address <= last;
  }
};

struct MemRange {
  uint32_t first;
  uint32_t last;

  bool contains(uint32_t address) const {
    return address >= first && address <= last;
  }
};

struct Config {
  std::filesystem::path output;
  uint8_t events = static_cast<uint8_t>(EventType::Cpu) |
                   static_cast<uint8_t>(EventType::Bank) |
                   static_cast<uint8_t>(EventType::Vram) |
                   static_cast<uint8_t>(EventType::Mem) |
                   static_cast<uint8_t>(EventType::BgCell) |
                   static_cast<uint8_t>(EventType::SpriteRow);
  std::vector<PcRange> cpu_pc;
  std::vector<AddressRange> vram_address;
  uint8_t vram_roles = kAllVramRoles;
  uint8_t mem_initiators = kAllMemInitiators;
  uint8_t mem_accesses = kAllMemAccesses;
  uint16_t mem_spaces = kAllMemSpaces;
  uint8_t origin_statuses = kAllOriginStatuses;
  std::vector<MemRange> mem_address;
  std::vector<MemRange> mem_offset;
  std::vector<PcRange> origin_pc;
  Format format = Format::Auto;

  bool enabled() const { return !output.empty(); }
  bool includes(EventType type) const {
    return (events & static_cast<uint8_t>(type)) != 0;
  }
  bool includes(VramRole role) const {
    return (vram_roles & (1u << static_cast<uint8_t>(role))) != 0;
  }
  bool includes_vram_address(uint16_t address) const {
    return vram_address.empty() ||
           std::any_of(vram_address.begin(), vram_address.end(),
                       [address](const AddressRange& range) {
                         return range.contains(address);
                       });
  }
  bool includes(MemInitiator value) const {
    return (mem_initiators & (1u << static_cast<uint8_t>(value))) != 0;
  }
  bool includes(MemAccess value) const {
    return (mem_accesses & (1u << static_cast<uint8_t>(value))) != 0;
  }
  bool includes(MemSpace value) const {
    return (mem_spaces & (1u << static_cast<uint8_t>(value))) != 0;
  }
  bool includes(OriginStatus value) const {
    return (origin_statuses & (1u << static_cast<uint8_t>(value))) != 0;
  }
  static bool includes_range(const std::vector<MemRange>& ranges,
                             uint32_t value) {
    return ranges.empty() ||
           std::any_of(ranges.begin(), ranges.end(),
                       [value](const MemRange& range) {
                         return range.contains(value);
                       });
  }
  static bool includes_pc(const std::vector<PcRange>& ranges,
                          uint32_t value) {
    return ranges.empty() ||
           std::any_of(ranges.begin(), ranges.end(),
                       [value](const PcRange& range) {
                         return range.contains(value);
                       });
  }
};

inline std::string trim(std::string value) {
  const auto not_space = [](unsigned char c) { return !std::isspace(c); };
  value.erase(value.begin(),
              std::find_if(value.begin(), value.end(), not_space));
  value.erase(std::find_if(value.rbegin(), value.rend(), not_space).base(),
              value.end());
  return value;
}

inline std::string lower(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  return value;
}

inline uint32_t parse_number(const std::string& text, uint32_t maximum,
                             const char* description) {
  const std::string value = trim(text);
  if (value.empty() || value.front() == '-') {
    throw std::runtime_error(std::string("invalid ") + description + ": " + text);
  }
  size_t parsed = 0;
  unsigned long long number = 0;
  try {
    number = std::stoull(value, &parsed, 0);
  } catch (const std::exception&) {
    throw std::runtime_error(std::string("invalid ") + description + ": " + text);
  }
  if (parsed != value.size() || number > maximum) {
    throw std::runtime_error(std::string("invalid ") + description + ": " + text);
  }
  return static_cast<uint32_t>(number);
}

inline PcRange parse_pc_range(const std::string& text) {
  const size_t separator = text.find('-');
  if (separator == std::string::npos || text.find('-', separator + 1) != std::string::npos) {
    throw std::runtime_error("CPU PC range must be START-END: " + text);
  }
  PcRange range{parse_number(text.substr(0, separator), 0x0f'ffff, "CPU PC"),
                parse_number(text.substr(separator + 1), 0x0f'ffff, "CPU PC")};
  if (range.first > range.last) {
    throw std::runtime_error("CPU PC range start exceeds end: " + text);
  }
  return range;
}

inline std::vector<PcRange> parse_pc_ranges(const std::string& text) {
  std::vector<PcRange> ranges;
  std::istringstream stream(text);
  std::string token;
  while (std::getline(stream, token, ',')) {
    token = trim(token);
    if (token.empty()) {
      throw std::runtime_error("CPU PC range list contains an empty item: " +
                               text);
    }
    ranges.push_back(parse_pc_range(token));
  }
  if (ranges.empty() || (!text.empty() && text.back() == ',')) {
    throw std::runtime_error("CPU PC range list must not be empty: " + text);
  }
  return ranges;
}

inline std::vector<AddressRange> parse_address_ranges(const std::string& text) {
  std::vector<AddressRange> ranges;
  std::istringstream stream(text);
  std::string token;
  while (std::getline(stream, token, ',')) {
    token = trim(token);
    if (token.empty()) {
      throw std::runtime_error("VRAM address range list contains an empty item: " +
                               text);
    }
    const size_t separator = token.find('-');
    uint32_t first;
    uint32_t last;
    if (separator == std::string::npos) {
      first = last = parse_number(token, 0xffff, "VRAM address");
    } else {
      if (separator == 0 || separator + 1 == token.size() ||
          token.find('-', separator + 1) != std::string::npos) {
        throw std::runtime_error(
            "VRAM address range must be ADDR or START-END: " + token);
      }
      first = parse_number(token.substr(0, separator), 0xffff, "VRAM address");
      last = parse_number(token.substr(separator + 1), 0xffff, "VRAM address");
      if (first > last) {
        throw std::runtime_error("VRAM address range start exceeds end: " + token);
      }
    }
    ranges.push_back(
        {static_cast<uint16_t>(first), static_cast<uint16_t>(last)});
  }
  if (ranges.empty() || (!text.empty() && text.back() == ',')) {
    throw std::runtime_error("VRAM address range list must not be empty: " + text);
  }
  return ranges;
}

inline const char* vram_role_name(VramRole role) {
  switch (role) {
    case VramRole::Screen1Map: return "screen1_map";
    case VramRole::Screen1Tile: return "screen1_tile";
    case VramRole::Screen2Map: return "screen2_map";
    case VramRole::Screen2Tile: return "screen2_tile";
    case VramRole::SpriteTable: return "sprite_table";
    case VramRole::SpriteTile: return "sprite_tile";
  }
  return "unknown";
}

inline VramRole vram_role_from_code(uint8_t code) {
  if (code > static_cast<uint8_t>(VramRole::SpriteTile)) {
    throw std::runtime_error("invalid VRAM role code: " + std::to_string(code));
  }
  return static_cast<VramRole>(code);
}

inline uint8_t parse_vram_roles(const std::string& text) {
  uint8_t result = 0;
  std::istringstream stream(text);
  std::string token;
  while (std::getline(stream, token, ',')) {
    token = lower(trim(token));
    if (token.empty()) {
      throw std::runtime_error("VRAM role list contains an empty item: " + text);
    }
    if (token == "all") {
      result |= kAllVramRoles;
    } else if (token == "screen1_map") {
      result |= 1u << static_cast<uint8_t>(VramRole::Screen1Map);
    } else if (token == "screen1_tile") {
      result |= 1u << static_cast<uint8_t>(VramRole::Screen1Tile);
    } else if (token == "screen2_map") {
      result |= 1u << static_cast<uint8_t>(VramRole::Screen2Map);
    } else if (token == "screen2_tile") {
      result |= 1u << static_cast<uint8_t>(VramRole::Screen2Tile);
    } else if (token == "sprite_table") {
      result |= 1u << static_cast<uint8_t>(VramRole::SpriteTable);
    } else if (token == "sprite_tile") {
      result |= 1u << static_cast<uint8_t>(VramRole::SpriteTile);
    } else {
      throw std::runtime_error("unknown VRAM role: " + token);
    }
  }
  if (result == 0 || (!text.empty() && text.back() == ',')) {
    throw std::runtime_error("VRAM role list must not be empty: " + text);
  }
  return result;
}

inline std::vector<MemRange> parse_mem_ranges(const std::string& text,
                                              uint32_t maximum,
                                              const char* description) {
  std::vector<MemRange> ranges;
  std::istringstream stream(text);
  std::string token;
  while (std::getline(stream, token, ',')) {
    token = trim(token);
    if (token.empty()) {
      throw std::runtime_error(std::string(description) +
                               " range list contains an empty item: " + text);
    }
    const size_t separator = token.find('-');
    uint32_t first;
    uint32_t last;
    if (separator == std::string::npos) {
      first = last = parse_number(token, maximum, description);
    } else {
      if (separator == 0 || separator + 1 == token.size() ||
          token.find('-', separator + 1) != std::string::npos) {
        throw std::runtime_error(std::string(description) +
                                 " range must be ADDR or START-END: " + token);
      }
      first = parse_number(token.substr(0, separator), maximum, description);
      last = parse_number(token.substr(separator + 1), maximum, description);
      if (first > last) {
        throw std::runtime_error(std::string(description) +
                                 " range start exceeds end: " + token);
      }
    }
    ranges.push_back({first, last});
  }
  if (ranges.empty() || (!text.empty() && text.back() == ',')) {
    throw std::runtime_error(std::string(description) +
                             " range list must not be empty: " + text);
  }
  return ranges;
}

template <typename Enum>
inline uint32_t enum_bit(Enum value) {
  return 1u << static_cast<uint8_t>(value);
}

inline uint8_t parse_mem_initiators(const std::string& text) {
  uint8_t result = 0;
  std::istringstream stream(text);
  std::string token;
  while (std::getline(stream, token, ',')) {
    token = lower(trim(token));
    if (token == "all") result |= kAllMemInitiators;
    else if (token == "cpu") result |= enum_bit(MemInitiator::Cpu);
    else if (token == "gdma") result |= enum_bit(MemInitiator::Gdma);
    else if (token == "sdma") result |= enum_bit(MemInitiator::Sdma);
    else throw std::runtime_error("unknown memory initiator: " + token);
  }
  if (result == 0 || (!text.empty() && text.back() == ','))
    throw std::runtime_error("memory initiator list must not be empty: " + text);
  return result;
}

inline uint8_t parse_mem_accesses(const std::string& text) {
  uint8_t result = 0;
  std::istringstream stream(text);
  std::string token;
  while (std::getline(stream, token, ',')) {
    token = lower(trim(token));
    if (token == "all") result |= kAllMemAccesses;
    else if (token == "read") result |= enum_bit(MemAccess::Read);
    else if (token == "write") result |= enum_bit(MemAccess::Write);
    else throw std::runtime_error("unknown memory access: " + token);
  }
  if (result == 0 || (!text.empty() && text.back() == ','))
    throw std::runtime_error("memory access list must not be empty: " + text);
  return result;
}

inline const char* mem_space_name(MemSpace value) {
  switch (value) {
    case MemSpace::Iram: return "iram";
    case MemSpace::CartSram: return "cart_sram";
    case MemSpace::CartRom0: return "cart_rom0";
    case MemSpace::CartRom1: return "cart_rom1";
    case MemSpace::CartRomLinear: return "cart_rom_linear";
    case MemSpace::BootRom: return "boot_rom";
    case MemSpace::Unmapped: return "unmapped";
    case MemSpace::AbsentSram: return "absent_sram";
  }
  return "unknown";
}

inline MemInitiator mem_initiator_from_code(uint8_t code) {
  if (code > static_cast<uint8_t>(MemInitiator::Sdma))
    throw std::runtime_error("invalid memory initiator code: " +
                             std::to_string(code));
  return static_cast<MemInitiator>(code);
}

inline MemSpace mem_space_from_code(uint8_t code) {
  if (code < static_cast<uint8_t>(MemSpace::Iram) ||
      code > static_cast<uint8_t>(MemSpace::AbsentSram))
    throw std::runtime_error("invalid memory space code: " +
                             std::to_string(code));
  return static_cast<MemSpace>(code);
}

inline OriginStatus origin_status_from_code(uint8_t code) {
  if (code < static_cast<uint8_t>(OriginStatus::Exact) ||
      code > static_cast<uint8_t>(OriginStatus::NotApplicable))
    throw std::runtime_error("invalid origin status code: " +
                             std::to_string(code));
  return static_cast<OriginStatus>(code);
}

inline uint16_t parse_mem_spaces(const std::string& text) {
  uint16_t result = 0;
  std::istringstream stream(text);
  std::string token;
  while (std::getline(stream, token, ',')) {
    token = lower(trim(token));
    if (token == "all") result |= kAllMemSpaces;
    else if (token == "iram") result |= enum_bit(MemSpace::Iram);
    else if (token == "cart_sram") result |= enum_bit(MemSpace::CartSram);
    else if (token == "cart_rom0") result |= enum_bit(MemSpace::CartRom0);
    else if (token == "cart_rom1") result |= enum_bit(MemSpace::CartRom1);
    else if (token == "cart_rom_linear") result |= enum_bit(MemSpace::CartRomLinear);
    else if (token == "boot_rom") result |= enum_bit(MemSpace::BootRom);
    else if (token == "unmapped") result |= enum_bit(MemSpace::Unmapped);
    else if (token == "absent_sram") result |= enum_bit(MemSpace::AbsentSram);
    else throw std::runtime_error("unknown memory space: " + token);
  }
  if (result == 0 || (!text.empty() && text.back() == ','))
    throw std::runtime_error("memory space list must not be empty: " + text);
  return result;
}

inline uint8_t parse_origin_statuses(const std::string& text) {
  uint8_t result = 0;
  std::istringstream stream(text);
  std::string token;
  while (std::getline(stream, token, ',')) {
    token = lower(trim(token));
    if (token == "all") result |= kAllOriginStatuses;
    else if (token == "exact") result |= enum_bit(OriginStatus::Exact);
    else if (token == "unattributed") result |= enum_bit(OriginStatus::Unattributed);
    else if (token == "not_applicable") result |= enum_bit(OriginStatus::NotApplicable);
    else throw std::runtime_error("unknown origin status: " + token);
  }
  if (result == 0 || (!text.empty() && text.back() == ','))
    throw std::runtime_error("origin status list must not be empty: " + text);
  return result;
}

inline uint8_t parse_events(const std::string& text) {
  uint8_t result = 0;
  std::istringstream stream(text);
  std::string token;
  while (std::getline(stream, token, ',')) {
    token = lower(trim(token));
    if (token == "all") {
      result |= static_cast<uint8_t>(EventType::Cpu) |
                static_cast<uint8_t>(EventType::Bank) |
                static_cast<uint8_t>(EventType::Vram) |
                static_cast<uint8_t>(EventType::Mem) |
                static_cast<uint8_t>(EventType::BgCell) |
                static_cast<uint8_t>(EventType::SpriteRow);
    } else if (token == "cpu") {
      result |= static_cast<uint8_t>(EventType::Cpu);
    } else if (token == "bank") {
      result |= static_cast<uint8_t>(EventType::Bank);
    } else if (token == "vram") {
      result |= static_cast<uint8_t>(EventType::Vram);
    } else if (token == "mem") {
      result |= static_cast<uint8_t>(EventType::Mem);
    } else if (token == "bg_cell") {
      result |= static_cast<uint8_t>(EventType::BgCell);
    } else if (token == "sprite_row") {
      result |= static_cast<uint8_t>(EventType::SpriteRow);
    } else {
      throw std::runtime_error("unknown trace event type: " + token);
    }
  }
  if (result == 0) throw std::runtime_error("trace event list must not be empty");
  return result;
}

inline Format parse_format(const std::string& text) {
  const std::string value = lower(trim(text));
  if (value == "auto") return Format::Auto;
  if (value == "csv") return Format::Csv;
  if (value == "jsonl") return Format::Jsonl;
  throw std::runtime_error("trace format must be csv or jsonl: " + text);
}

inline void parse_config(std::istream& input, Config& config,
                         const std::string& source = "trace config") {
  std::string line;
  unsigned line_number = 0;
  while (std::getline(input, line)) {
    ++line_number;
    const size_t comment = line.find('#');
    if (comment != std::string::npos) line.erase(comment);
    line = trim(line);
    if (line.empty()) continue;
    const size_t separator = line.find('=');
    if (separator == std::string::npos) {
      throw std::runtime_error(source + ":" + std::to_string(line_number) +
                               ": expected KEY=VALUE");
    }
    const std::string key = lower(trim(line.substr(0, separator)));
    const std::string value = trim(line.substr(separator + 1));
    try {
      if (key == "output") config.output = value;
      else if (key == "events") config.events = parse_events(value);
      else if (key == "cpu_pc") config.cpu_pc = parse_pc_ranges(value);
      else if (key == "vram_address") config.vram_address = parse_address_ranges(value);
      else if (key == "vram_role") config.vram_roles = parse_vram_roles(value);
      else if (key == "mem_initiator") config.mem_initiators = parse_mem_initiators(value);
      else if (key == "mem_access") config.mem_accesses = parse_mem_accesses(value);
      else if (key == "mem_address") config.mem_address = parse_mem_ranges(value, 0xfffff, "memory address");
      else if (key == "mem_space") config.mem_spaces = parse_mem_spaces(value);
      else if (key == "mem_offset") config.mem_offset = parse_mem_ranges(value, 0xffffff, "memory offset");
      else if (key == "mem_origin") config.origin_statuses = parse_origin_statuses(value);
      else if (key == "origin_pc") config.origin_pc = parse_pc_ranges(value);
      else if (key == "format") config.format = parse_format(value);
      else throw std::runtime_error("unknown key: " + key);
    } catch (const std::exception& error) {
      throw std::runtime_error(source + ":" + std::to_string(line_number) +
                               ": " + error.what());
    }
  }
}

inline void parse_config_file(const std::filesystem::path& path, Config& config) {
  std::ifstream input(path);
  if (!input) throw std::runtime_error("cannot open trace config " + path.string());
  parse_config(input, config, path.string());
}

inline Format resolved_format(const Config& config) {
  if (config.format != Format::Auto) return config.format;
  const std::string extension = lower(config.output.extension().string());
  return (extension == ".jsonl" || extension == ".ndjson") ? Format::Jsonl
                                                              : Format::Csv;
}

struct Event {
  uint64_t cycle;
  EventType type;
  std::optional<uint32_t> physical_pc;
  std::optional<uint32_t> cs;
  std::optional<uint32_t> ip;
  std::optional<uint32_t> address;
  std::optional<uint32_t> value;
  std::optional<VramRole> role;
  std::optional<MemInitiator> initiator = std::nullopt;
  std::optional<MemAccess> access = std::nullopt;
  std::optional<uint32_t> byte_enable = std::nullopt;
  std::optional<MemSpace> space = std::nullopt;
  std::optional<uint32_t> mapped_offset = std::nullopt;
  std::optional<uint32_t> instruction_id = std::nullopt;
  std::optional<uint32_t> origin_pc = std::nullopt;
  std::optional<OriginStatus> origin_status = std::nullopt;
  std::optional<uint32_t> fetch_value = std::nullopt;
  std::optional<uint32_t> fetch_collision = std::nullopt;
  std::optional<uint32_t> bg_layer = std::nullopt;
  std::optional<uint32_t> map_address = std::nullopt;
  std::optional<uint32_t> map_value = std::nullopt;
  std::optional<uint32_t> map_x = std::nullopt;
  std::optional<uint32_t> map_y = std::nullopt;
  std::optional<uint32_t> tile_bank_enabled = std::nullopt;
  std::optional<uint32_t> tile_index = std::nullopt;
  std::optional<uint32_t> palette = std::nullopt;
  std::optional<uint32_t> hflip = std::nullopt;
  std::optional<uint32_t> vflip = std::nullopt;
  std::optional<uint32_t> bpp = std::nullopt;
  std::optional<uint32_t> packed = std::nullopt;
  std::optional<uint32_t> tile_row = std::nullopt;
  std::optional<uint32_t> tile_row_address = std::nullopt;
  std::optional<uint32_t> tile_row_bytes = std::nullopt;
  std::optional<uint32_t> tile_row_value = std::nullopt;
  std::optional<uint32_t> map_collision = std::nullopt;
  std::optional<uint32_t> tile_row_collision = std::nullopt;
  std::optional<uint32_t> sprite_table_address = std::nullopt;
  std::optional<uint32_t> sprite_table_value = std::nullopt;
  std::optional<uint32_t> sprite_table_collision = std::nullopt;
  std::optional<uint32_t> sprite_line_y = std::nullopt;
  std::optional<uint32_t> sprite_line_slot = std::nullopt;
  std::optional<uint32_t> sprite_table_generation = std::nullopt;
  std::optional<uint32_t> sprite_line_epoch = std::nullopt;
};

inline const char* event_name(EventType type) {
  switch (type) {
    case EventType::Cpu: return "cpu";
    case EventType::Bank: return "bank";
    case EventType::Vram: return "vram";
    case EventType::Mem: return "mem";
    case EventType::BgCell: return "bg_cell";
    case EventType::SpriteRow: return "sprite_row";
  }
  return "unknown";
}

inline const char* initiator_name(MemInitiator value) {
  switch (value) {
    case MemInitiator::Cpu: return "cpu";
    case MemInitiator::Gdma: return "gdma";
    case MemInitiator::Sdma: return "sdma";
  }
  return "unknown";
}

inline const char* access_name(MemAccess value) {
  return value == MemAccess::Write ? "write" : "read";
}

inline const char* origin_status_name(OriginStatus value) {
  switch (value) {
    case OriginStatus::Exact: return "exact";
    case OriginStatus::Unattributed: return "unattributed";
    case OriginStatus::NotApplicable: return "not_applicable";
  }
  return "unknown";
}

class Writer {
 public:
  Writer(std::ostream& output, Format format, unsigned schema = 5)
      : output_(output), format_(format), schema_(schema) {
    if (schema_ != 5 && schema_ != 6) {
      throw std::runtime_error("structured trace writer schema must be 5 or 6");
    }
    if (format_ == Format::Csv) {
      output_ << "cycle,event,physical_pc,cs,ip,address,value,role,"
                  "initiator,access,byte_enable,space,mapped_offset,"
                  "instruction_id,origin_pc,origin_status,fetch_value,"
                  "fetch_collision,bg_layer,map_address,map_value,map_x,map_y,"
                  "tile_bank_enabled,tile_index,palette,hflip,vflip,bpp,packed,"
                  "tile_row,tile_row_address,tile_row_bytes,tile_row_value,"
                  "map_collision,tile_row_collision";
      if (schema_ >= 6) {
        output_ << ",sprite_table_address,sprite_table_value,"
                   "sprite_table_collision,sprite_line_y,sprite_line_slot,"
                   "sprite_table_generation,sprite_line_epoch";
      }
      output_ << '\n';
    }
  }

  void write(const Event& event) {
    if (event.type == EventType::SpriteRow && schema_ < 6) {
      throw std::runtime_error("sprite_row requires structured trace schema v6");
    }
    if (format_ == Format::Csv) write_csv(event);
    else write_jsonl(event);
    if (!output_) throw std::runtime_error("failed to write structured trace");
  }

 private:
  static void csv_optional(std::ostream& output,
                           const std::optional<uint32_t>& value) {
    if (value) output << *value;
  }

  static void json_optional(std::ostream& output, const char* key,
                            const std::optional<uint32_t>& value) {
    output << ",\"" << key << "\":";
    if (value) output << *value;
    else output << "null";
  }

  void write_csv(const Event& event) {
    output_ << event.cycle << ',' << event_name(event.type) << ',';
    csv_optional(output_, event.physical_pc);
    output_ << ',';
    csv_optional(output_, event.cs);
    output_ << ',';
    csv_optional(output_, event.ip);
    output_ << ',';
    csv_optional(output_, event.address);
    output_ << ',';
    csv_optional(output_, event.value);
    output_ << ',';
    if (event.role) output_ << vram_role_name(*event.role);
    output_ << ',';
    if (event.initiator) output_ << initiator_name(*event.initiator);
    output_ << ',';
    if (event.access) output_ << access_name(*event.access);
    output_ << ',';
    csv_optional(output_, event.byte_enable);
    output_ << ',';
    if (event.space) output_ << mem_space_name(*event.space);
    output_ << ',';
    csv_optional(output_, event.mapped_offset);
    output_ << ',';
    csv_optional(output_, event.instruction_id);
    output_ << ',';
    csv_optional(output_, event.origin_pc);
    output_ << ',';
    if (event.origin_status) output_ << origin_status_name(*event.origin_status);
    output_ << ',';
    csv_optional(output_, event.fetch_value);
    output_ << ',';
    csv_optional(output_, event.fetch_collision);
    output_ << ',';
    csv_optional(output_, event.bg_layer);
    output_ << ',';
    csv_optional(output_, event.map_address);
    output_ << ',';
    csv_optional(output_, event.map_value);
    output_ << ',';
    csv_optional(output_, event.map_x);
    output_ << ',';
    csv_optional(output_, event.map_y);
    output_ << ',';
    csv_optional(output_, event.tile_bank_enabled);
    output_ << ',';
    csv_optional(output_, event.tile_index);
    output_ << ',';
    csv_optional(output_, event.palette);
    output_ << ',';
    csv_optional(output_, event.hflip);
    output_ << ',';
    csv_optional(output_, event.vflip);
    output_ << ',';
    csv_optional(output_, event.bpp);
    output_ << ',';
    csv_optional(output_, event.packed);
    output_ << ',';
    csv_optional(output_, event.tile_row);
    output_ << ',';
    csv_optional(output_, event.tile_row_address);
    output_ << ',';
    csv_optional(output_, event.tile_row_bytes);
    output_ << ',';
    csv_optional(output_, event.tile_row_value);
    output_ << ',';
    csv_optional(output_, event.map_collision);
    output_ << ',';
    csv_optional(output_, event.tile_row_collision);
    if (schema_ >= 6) {
      output_ << ',';
      csv_optional(output_, event.sprite_table_address);
      output_ << ',';
      csv_optional(output_, event.sprite_table_value);
      output_ << ',';
      csv_optional(output_, event.sprite_table_collision);
      output_ << ',';
      csv_optional(output_, event.sprite_line_y);
      output_ << ',';
      csv_optional(output_, event.sprite_line_slot);
      output_ << ',';
      csv_optional(output_, event.sprite_table_generation);
      output_ << ',';
      csv_optional(output_, event.sprite_line_epoch);
    }
    output_ << '\n';
  }

  void write_jsonl(const Event& event) {
    output_ << "{\"cycle\":" << event.cycle << ",\"event\":\""
            << event_name(event.type) << '"';
    json_optional(output_, "physical_pc", event.physical_pc);
    json_optional(output_, "cs", event.cs);
    json_optional(output_, "ip", event.ip);
    json_optional(output_, "address", event.address);
    json_optional(output_, "value", event.value);
    output_ << ",\"role\":";
    if (event.role) output_ << '\"' << vram_role_name(*event.role) << '\"';
    else output_ << "null";
    output_ << ",\"initiator\":";
    if (event.initiator) output_ << '\"' << initiator_name(*event.initiator) << '\"';
    else output_ << "null";
    output_ << ",\"access\":";
    if (event.access) output_ << '\"' << access_name(*event.access) << '\"';
    else output_ << "null";
    json_optional(output_, "byte_enable", event.byte_enable);
    output_ << ",\"space\":";
    if (event.space) output_ << '\"' << mem_space_name(*event.space) << '\"';
    else output_ << "null";
    json_optional(output_, "mapped_offset", event.mapped_offset);
    json_optional(output_, "instruction_id", event.instruction_id);
    json_optional(output_, "origin_pc", event.origin_pc);
    output_ << ",\"origin_status\":";
    if (event.origin_status)
      output_ << '\"' << origin_status_name(*event.origin_status) << '\"';
    else output_ << "null";
    json_optional(output_, "fetch_value", event.fetch_value);
    json_optional(output_, "fetch_collision", event.fetch_collision);
    json_optional(output_, "bg_layer", event.bg_layer);
    json_optional(output_, "map_address", event.map_address);
    json_optional(output_, "map_value", event.map_value);
    json_optional(output_, "map_x", event.map_x);
    json_optional(output_, "map_y", event.map_y);
    json_optional(output_, "tile_bank_enabled", event.tile_bank_enabled);
    json_optional(output_, "tile_index", event.tile_index);
    json_optional(output_, "palette", event.palette);
    json_optional(output_, "hflip", event.hflip);
    json_optional(output_, "vflip", event.vflip);
    json_optional(output_, "bpp", event.bpp);
    json_optional(output_, "packed", event.packed);
    json_optional(output_, "tile_row", event.tile_row);
    json_optional(output_, "tile_row_address", event.tile_row_address);
    json_optional(output_, "tile_row_bytes", event.tile_row_bytes);
    json_optional(output_, "tile_row_value", event.tile_row_value);
    json_optional(output_, "map_collision", event.map_collision);
    json_optional(output_, "tile_row_collision", event.tile_row_collision);
    if (schema_ >= 6) {
      json_optional(output_, "sprite_table_address", event.sprite_table_address);
      json_optional(output_, "sprite_table_value", event.sprite_table_value);
      json_optional(output_, "sprite_table_collision", event.sprite_table_collision);
      json_optional(output_, "sprite_line_y", event.sprite_line_y);
      json_optional(output_, "sprite_line_slot", event.sprite_line_slot);
      json_optional(output_, "sprite_table_generation",
                    event.sprite_table_generation);
      json_optional(output_, "sprite_line_epoch", event.sprite_line_epoch);
    }
    output_ << "}\n";
  }

  std::ostream& output_;
  Format format_;
  unsigned schema_;
};

class Logger {
 public:
  explicit Logger(const Config& config) : config_(config) {
    if (!config_.enabled()) throw std::runtime_error("trace output path is empty");
    if (config_.output.has_parent_path()) {
      std::filesystem::create_directories(config_.output.parent_path());
    }
    output_.open(config_.output, std::ios::out | std::ios::trunc);
    if (!output_) throw std::runtime_error("cannot write " + config_.output.string());
    writer_ = std::make_unique<Writer>(
        output_, resolved_format(config_),
        config_.includes(EventType::SpriteRow) ? 6u : 5u);
  }

  void cpu(uint64_t cycle, uint32_t physical_pc, uint16_t cs, uint16_t ip) {
    if (!config_.includes(EventType::Cpu)) return;
    if (!Config::includes_pc(config_.cpu_pc, physical_pc)) return;
    writer_->write({cycle, EventType::Cpu, physical_pc, cs, ip,
                    std::nullopt, std::nullopt, std::nullopt});
  }

  void bank(uint64_t cycle, uint8_t address, uint8_t value,
            uint32_t instruction_id, uint32_t origin_pc,
            OriginStatus origin_status) {
    if (address < 0xc0 || address > 0xc3 || instruction_id == 0 ||
        origin_pc > 0x0f'ffff ||
        origin_status != OriginStatus::Exact) {
      throw std::runtime_error(
          "bank trace event requires C0-C3 and a nonzero exact CPU origin");
    }
    if (!config_.includes(EventType::Bank)) return;
    Event event{cycle, EventType::Bank, std::nullopt, std::nullopt,
                std::nullopt, address, value, std::nullopt};
    event.instruction_id = instruction_id;
    event.origin_pc = origin_pc;
    event.origin_status = origin_status;
    writer_->write(event);
  }

  void vram(uint64_t cycle, uint16_t address, VramRole role, uint16_t value,
            bool collision) {
    if (!config_.includes(EventType::Vram)) return;
    if (!config_.includes(role) || !config_.includes_vram_address(address)) return;
    Event event{cycle, EventType::Vram, std::nullopt, std::nullopt,
                std::nullopt, address, std::nullopt, role};
    event.fetch_value = value;
    event.fetch_collision = collision ? 1 : 0;
    writer_->write(event);
  }

  void bg_cell(uint64_t cycle, uint8_t bg_layer, uint16_t map_address,
               uint16_t map_value, uint8_t map_x, uint8_t map_y,
               bool tile_bank_enabled, uint16_t tile_index, uint8_t palette,
               bool hflip, bool vflip, uint8_t bpp, bool packed,
               uint8_t tile_row, uint16_t tile_row_address,
               uint8_t tile_row_bytes, uint32_t tile_row_value,
               bool map_collision, bool tile_row_collision) {
    const auto fail = [&](const std::string& invariant) -> void {
      std::ostringstream message;
      message << "invalid background-cell trace event: " << invariant
              << " [cycle=" << cycle
              << " layer=" << static_cast<unsigned>(bg_layer)
              << " map_address=0x" << std::hex << map_address
              << " map_value=0x" << map_value << std::dec
              << " map_xy=" << static_cast<unsigned>(map_x) << ','
              << static_cast<unsigned>(map_y)
              << " bank=" << tile_bank_enabled
              << " tile_index=" << tile_index
              << " palette=" << static_cast<unsigned>(palette)
              << " hflip=" << hflip << " vflip=" << vflip
              << " bpp=" << static_cast<unsigned>(bpp)
              << " packed=" << packed
              << " tile_row=" << static_cast<unsigned>(tile_row)
              << " row_address=0x" << std::hex << tile_row_address
              << " row_bytes=" << std::dec
              << static_cast<unsigned>(tile_row_bytes)
              << " row_value=0x" << std::hex << tile_row_value << std::dec
              << " map_collision=" << map_collision
              << " row_collision=" << tile_row_collision << ']';
      throw std::runtime_error(message.str());
    };
    const uint16_t decoded_tile_index =
        static_cast<uint16_t>((map_value & 0x01ffu) |
                              (tile_bank_enabled ? ((map_value >> 4) & 0x0200u)
                                                 : 0u));
    const uint8_t decoded_palette = (map_value >> 9) & 0x0f;
    const uint8_t decoded_hflip = (map_value >> 14) & 1;
    const uint8_t decoded_vflip = (map_value >> 15) & 1;
    const uint8_t decoded_map_x = (map_address >> 1) & 0x1f;
    const uint8_t decoded_map_y = (map_address >> 6) & 0x1f;
    if (bg_layer != 1 && bg_layer != 2) fail("bg_layer must be 1 or 2");
    if (map_address & 1) fail("map_address must be word-aligned");
    if (map_x > 31 || map_y > 31) fail("map coordinates must be within 0..31");
    if (map_x != decoded_map_x || map_y != decoded_map_y) {
      fail("map coordinates do not match map_address; expected " +
           std::to_string(decoded_map_x) + "," +
           std::to_string(decoded_map_y));
    }
    if (tile_index > 1023) fail("tile_index must be within 0..1023");
    if (tile_index != decoded_tile_index) {
      fail("tile_index does not match map_value/tile_bank_enabled; expected " +
           std::to_string(decoded_tile_index));
    }
    if (palette > 15) fail("palette must be within 0..15");
    if (palette != decoded_palette) {
      fail("palette does not match map_value; expected " +
           std::to_string(decoded_palette));
    }
    if (hflip != (decoded_hflip != 0)) {
      fail("hflip does not match map_value; expected " +
           std::to_string(decoded_hflip));
    }
    if (vflip != (decoded_vflip != 0)) {
      fail("vflip does not match map_value; expected " +
           std::to_string(decoded_vflip));
    }
    if (bpp != 2 && bpp != 4) fail("bpp must be 2 or 4");
    if (tile_row > 7) fail("tile_row must be within 0..7");
    const uint8_t expected_row_bytes = bpp == 2 ? 2 : 4;
    if (tile_row_bytes != expected_row_bytes) {
      fail("tile_row_bytes does not match bpp; expected " +
           std::to_string(expected_row_bytes));
    }
    const uint32_t expected_row_address =
        (bpp == 2 ? 0x2000u : 0x4000u) +
        static_cast<uint32_t>(tile_index) * expected_row_bytes * 8u +
        static_cast<uint32_t>(tile_row) * expected_row_bytes;
    if (tile_row_address != expected_row_address) {
      std::ostringstream expected;
      expected << "tile_row_address does not match decoded tile row; expected 0x"
               << std::hex << expected_row_address;
      fail(expected.str());
    }
    if (tile_row_bytes == 2 && tile_row_value > 0xffffu) {
      fail("tile_row_value exceeds the 16-bit 2bpp row width");
    }
    if (!config_.includes(EventType::BgCell)) return;
    writer_->write({cycle,
                    EventType::BgCell,
                    std::nullopt,
                    std::nullopt,
                    std::nullopt,
                    std::nullopt,
                    std::nullopt,
                    std::nullopt,
                    std::nullopt,
                    std::nullopt,
                    std::nullopt,
                    std::nullopt,
                    std::nullopt,
                    std::nullopt,
                    std::nullopt,
                    std::nullopt,
                    std::nullopt,
                    std::nullopt,
                    bg_layer,
                    map_address,
                    map_value,
                    map_x,
                    map_y,
                    tile_bank_enabled ? 1u : 0u,
                    tile_index,
                    palette,
                    hflip ? 1u : 0u,
                    vflip ? 1u : 0u,
                    bpp,
                    packed ? 1u : 0u,
                    tile_row,
                    tile_row_address,
                    tile_row_bytes,
                    tile_row_value,
                    map_collision ? 1u : 0u,
                    tile_row_collision ? 1u : 0u});
  }

  void sprite_row(uint64_t cycle, uint16_t table_address,
                  uint32_t table_value, bool table_collision,
                  uint32_t table_generation,
                  uint8_t line_y, uint8_t line_slot, uint32_t line_epoch,
                  uint8_t bpp,
                  bool packed, uint16_t row_address, uint32_t row_value,
                  bool row_collision) {
    const auto fail = [&](const std::string& invariant) -> void {
      std::ostringstream message;
      message << "invalid sprite-row trace event: " << invariant
              << " [cycle=" << cycle
              << " table_address=0x" << std::hex << table_address
              << " table_value=0x" << table_value << std::dec
              << " table_generation=" << table_generation
              << " line_y=" << static_cast<unsigned>(line_y)
              << " line_slot=" << static_cast<unsigned>(line_slot)
              << " line_epoch=" << line_epoch
              << " bpp=" << static_cast<unsigned>(bpp)
              << " packed=" << packed
              << " row_address=0x" << std::hex << row_address
              << " row_value=0x" << row_value << std::dec
              << " table_collision=" << table_collision
              << " row_collision=" << row_collision << ']';
      throw std::runtime_error(message.str());
    };
    if (table_address & 3) fail("sprite_table_address must be 4-byte aligned");
    if (line_slot > 31) fail("sprite_line_slot must be within 0..31");
    if (bpp != 2 && bpp != 4) fail("bpp must be 2 or 4");

    const uint16_t tile_index = table_value & 0x01ffu;
    const uint8_t palette = 8u | ((table_value >> 9) & 7u);
    const bool hflip = ((table_value >> 14) & 1u) != 0;
    const bool vflip = ((table_value >> 15) & 1u) != 0;
    const uint8_t sprite_y = (table_value >> 16) & 0xffu;
    const uint8_t delta = static_cast<uint8_t>(line_y - sprite_y);
    if (delta >= 8) fail("sprite is not vertically active on sprite_line_y");
    const uint8_t tile_row = vflip ? static_cast<uint8_t>(7 - delta) : delta;
    const uint8_t row_bytes = bpp == 2 ? 2 : 4;
    const uint32_t expected_address =
        (bpp == 2 ? 0x2000u : 0x4000u) +
        static_cast<uint32_t>(tile_index) * row_bytes * 8u +
        static_cast<uint32_t>(tile_row) * row_bytes;
    if (row_address != expected_address) {
      std::ostringstream expected;
      expected << "tile_row_address does not match descriptor/line; expected 0x"
               << std::hex << expected_address;
      fail(expected.str());
    }
    if (bpp == 2 && row_value > 0xffffu) {
      fail("tile_row_value exceeds the 16-bit 2bpp row width");
    }
    if (!config_.includes(EventType::SpriteRow)) return;

    Event event{cycle, EventType::SpriteRow, std::nullopt, std::nullopt,
                std::nullopt, std::nullopt, std::nullopt, std::nullopt};
    event.tile_index = tile_index;
    event.palette = palette;
    event.hflip = hflip ? 1u : 0u;
    event.vflip = vflip ? 1u : 0u;
    event.bpp = bpp;
    event.packed = packed ? 1u : 0u;
    event.tile_row = tile_row;
    event.tile_row_address = row_address;
    event.tile_row_bytes = row_bytes;
    event.tile_row_value = row_value;
    event.tile_row_collision = row_collision ? 1u : 0u;
    event.sprite_table_address = table_address;
    event.sprite_table_value = table_value;
    event.sprite_table_collision = table_collision ? 1u : 0u;
    event.sprite_line_y = line_y;
    event.sprite_line_slot = line_slot;
    event.sprite_table_generation = table_generation;
    event.sprite_line_epoch = line_epoch;
    writer_->write(event);
  }

  void mem(uint64_t cycle, MemInitiator initiator, MemAccess access,
           uint32_t address, uint16_t value, uint8_t byte_enable,
           MemSpace space, std::optional<uint32_t> mapped_offset,
           std::optional<uint32_t> instruction_id,
           std::optional<uint32_t> origin_pc, OriginStatus origin_status) {
    const bool cpu = initiator == MemInitiator::Cpu;
    const bool complete_origin = instruction_id.has_value() && origin_pc.has_value();
    if ((origin_status == OriginStatus::Exact && (!cpu || !complete_origin)) ||
        (origin_status == OriginStatus::Unattributed &&
         (!cpu || instruction_id || origin_pc)) ||
        (origin_status == OriginStatus::NotApplicable &&
         (cpu || instruction_id || origin_pc))) {
      throw std::runtime_error("invalid memory origin attribution");
    }
    if (!config_.includes(EventType::Mem) || !config_.includes(initiator) ||
        !config_.includes(access) || !config_.includes(space) ||
        !config_.includes(origin_status) ||
        !Config::includes_range(config_.mem_address, address) ||
        (mapped_offset &&
         !Config::includes_range(config_.mem_offset, *mapped_offset)) ||
        (!mapped_offset && !config_.mem_offset.empty()) ||
        (!config_.origin_pc.empty() &&
         (!origin_pc || !Config::includes_pc(config_.origin_pc, *origin_pc)))) {
      return;
    }
    writer_->write({cycle, EventType::Mem, std::nullopt, std::nullopt,
                    std::nullopt, address, value, std::nullopt,
                    initiator, access, byte_enable, space, mapped_offset,
                    instruction_id, origin_pc, origin_status});
  }

 private:
  Config config_;
  std::ofstream output_;
  std::unique_ptr<Writer> writer_;
};

}  // namespace swansong::trace
